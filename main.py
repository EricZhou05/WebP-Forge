import os
import subprocess
import shutil
import logging
import datetime
import argparse
import sys
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    TaskID,
)
from rich.panel import Panel
from rich.logging import RichHandler
from rich.table import Table

# 强制控制台输出使用 UTF-8
if sys.platform == "win32":
    import _locale
    _locale._getdefaultlocale = (lambda *args: ['zh_CN', 'utf8'])

console = Console()

def setup_logging(log_dir: Path):
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"compress_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(console=console, rich_tracebacks=True),
            logging.FileHandler(log_file, encoding='utf-8')
        ]
    )
    return log_file

def get_cwebp_path() -> str:
    local_cwebp = Path(__file__).resolve().parent / "bin" / "cwebp.exe"
    if local_cwebp.exists():
        return str(local_cwebp)
    return "cwebp"

def get_cwebp_cmd(input_file: Path, output_file: Path) -> list[str]:
    return [
        get_cwebp_path(),
        "-mt",  # 开启多线程榨干单核性能
        "-m", "6",
        "-q", "95",
        "-alpha_q", "100",
        "-alpha_method", "1",
        "-af",
        "-strong",
        "-sharpness", "7",
        "-sns", "80",
        "-segments", "4",
        "-partition_limit", "0",
        "-pass", "1",
        "-exact",
        str(input_file),
        "-o",
        str(output_file)
    ]

def worker(input_file: Path) -> dict:
    output_file = input_file.with_suffix('.webp')
    
    if output_file.exists() and output_file.stat().st_size > 0:
        return {'status': 'skipped', 'input': input_file, 'output': output_file}

    cmd = get_cwebp_cmd(input_file, output_file)
    
    try:
        # 【关键修复】显式指定 encoding='utf-8' 并在遇到解析不了的字符时忽略，防止 UnicodeDecodeError
        result = subprocess.run(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True, 
            encoding='utf-8', 
            errors='ignore',
            check=False
        )
        
        if result.returncode != 0:
            if output_file.exists():
                output_file.unlink()
            return {'status': 'error', 'input': input_file, 'error': result.stderr.strip()}
        
        orig_size = input_file.stat().st_size
        new_size = output_file.stat().st_size
        return {
            'status': 'success', 
            'input': input_file, 
            'output': output_file, 
            'orig_size': orig_size, 
            'new_size': new_size,
            'cmd': " ".join(cmd)
        }
        
    except Exception as e:
        if output_file.exists():
            output_file.unlink()
        return {'status': 'error', 'input': input_file, 'error': str(e)}

def move_originals(src_dir: Path, backup_dir: Path, image_files: list[Path], progress: Progress, task_id: TaskID, is_single_file: bool = False):
    for img_file in image_files:
        try:
            if is_single_file:
                # 单文件模式：直接在原位重命名，例如 1.png -> 1_forge.png
                dest_file = img_file.parent / f"{img_file.stem}_forge{img_file.suffix}"
                display_path = dest_file.name
            else:
                # 目录模式：保持原有的备份逻辑
                rel_path = img_file.relative_to(src_dir)
                dest_file = backup_dir / rel_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                display_path = str(rel_path)
            
            if dest_file.exists():
                dest_file.unlink()
            shutil.move(str(img_file), str(dest_file))
            logging.info(f"[MOVE] 已归档: {display_path}")
        except Exception as e:
            logging.error(f"[MOVE_ERROR] {img_file.name} 移动失败: {e}")
        
        progress.update(task_id, advance=1)

def main():
    parser = argparse.ArgumentParser(description="二次元插画高保真批量压缩工具")
    parser.add_argument("-s", "--src", help="源目录或文件")
    parser.add_argument("-b", "--backup", help="备份目录")
    parser.add_argument("-w", "--workers", type=int, default=max(1, os.cpu_count() - 1))
    args = parser.parse_args()

    console.print(Panel.fit("[bold magenta]WebP-Forge 极致压缩工具[/bold magenta]\n[cyan]高保真 / 多核并行 / 自动备份[/cyan]", border_style="magenta"))

    # 1. 获取源路径
    if not args.src:
        src_input = console.input("[bold green]输入源文件夹或图片文件 (支持直接拖入): [/bold green]").strip().strip("\"")
        src_path = Path(src_input).resolve()
    else:
        src_path = Path(args.src).resolve()

    if not src_path.exists():
        console.print(f"[bold red]错误: 路径不存在 {src_path}[/bold red]")
        return

    # 2. 判定处理模式并确定基础目录与待处理文件
    is_single_file = src_path.is_file()
    image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif'}

    if is_single_file:
        if src_path.suffix.lower() not in image_extensions:
            console.print(f"[bold red]错误: 不支持的文件格式 {src_path.suffix}[/bold red]")
            return
        src_dir = src_path.parent
        image_files = [src_path]
    else:
        src_dir = src_path
        with console.status("[bold yellow]正在扫描图片资源...", spinner="bouncingBall"):
            image_files = [f for f in src_dir.rglob("*") if f.is_file() and f.suffix.lower() in image_extensions]

    if not image_files:
        console.print("[yellow]未找到待处理的图片格式。[/yellow]")
        return

    # 3. 确定备份目录
    if is_single_file:
        backup_dir = src_dir # 实际上单文件模式不使用 backup_dir 路径拼接
    else:
        default_backup = src_dir.parent / f"{src_dir.name}_forge"
        
        if not args.backup:
            if not args.src: # 只有交互式运行才询问
                console.print(f"[cyan]建议备份目录: {default_backup}[/cyan]")
                backup_input = console.input(f"[bold green]输入备份文件夹 (回车使用建议): [/bold green]").strip().strip("\"")
                backup_dir = Path(backup_input).resolve() if backup_input else default_backup
            else:
                backup_dir = default_backup
        else:
            backup_dir = Path(args.backup).resolve()

    workers = args.workers

    log_file = setup_logging(src_dir / "logs")
    logging.info(f"=== 任务启动: {datetime.datetime.now()} ===")
    logging.info(f"源路径: {src_path}")
    logging.info(f"备份模式: {'单文件原位备份' if is_single_file else '目录归档'}")
    if not is_single_file:
        logging.info(f"备份路径: {backup_dir}")
    logging.info(f"并发数: {workers}")

    logging.info(f"待处理: {len(image_files)} 张")

    success_count = 0
    skipped_count = 0
    error_count = 0
    total_orig_size = 0
    total_new_size = 0

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(style="bright_black", complete_style="magenta"),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        "•",
        TextColumn("[bold cyan]{task.completed}/{task.total}[/bold cyan]"),
        TimeRemainingColumn(),
        expand=True
    )

    with progress:
        compress_task = progress.add_task("[white]执行极致压缩...", total=len(image_files))
        
        with ProcessPoolExecutor(max_workers=workers) as executor:
            future_to_file = {executor.submit(worker, f): f for f in image_files}
            
            for future in as_completed(future_to_file):
                res = future.result()
                if res['status'] == 'success':
                    success_count += 1
                    total_orig_size += res['orig_size']
                    total_new_size += res['new_size']
                    logging.info(f"[SUCCESS] {res['input'].name} | 参数: {res['cmd']}")
                elif res['status'] == 'skipped':
                    skipped_count += 1
                    logging.info(f"[SKIP] {res['input'].name} 已存在。")
                elif res['status'] == 'error':
                    error_count += 1
                    logging.error(f"[ERROR] {res['input'].name} -> {res['error']}")
                
                progress.update(compress_task, advance=1)

    # 4. 移动
    files_to_move = [f for f in image_files if f.with_suffix('.webp').exists() and f.exists()]
    if files_to_move:
        move_task_id = progress.add_task("[yellow]正在归档原图...", total=len(files_to_move))
        with progress:
            move_originals(src_dir, backup_dir, files_to_move, progress, move_task_id)

    # --- 改进的统计表 ---
    table = Table(title="📊 压缩任务总结", box=None, show_header=False)
    table.add_column("Key", style="bold cyan")
    table.add_column("Value")
    
    table.add_row("成功完成", f"[green]{success_count}[/green] 张")
    table.add_row("错误失败", f"[red]{error_count}[/red] 张")
    
    # 同时记录到日志文件
    logging.info("📊 压缩任务总结")
    logging.info(f"成功完成: {success_count} 张")
    logging.info(f"错误失败: {error_count} 张")

    if success_count > 0:
        reduction = total_orig_size - total_new_size
        reduction_percent = (reduction / total_orig_size) * 100
        table.add_row("原始总体积", f"{total_orig_size / (1024*1024):.2f} MB")
        table.add_row("压缩后体积", f"{total_new_size / (1024*1024):.2f} MB")
        table.add_row("空间缩减率", f"[bold green]{reduction_percent:.1f}%[/bold green] (节省 {reduction / (1024*1024):.2f} MB)")

        logging.info(f"原始总体积: {total_orig_size / (1024*1024):.2f} MB")
        logging.info(f"压缩后体积: {total_new_size / (1024*1024):.2f} MB")
        logging.info(f"空间缩减率: {reduction_percent:.1f}% (节省 {reduction / (1024*1024):.2f} MB)")

    console.print("\n", table)

    # 4. 移动
    files_to_move = [f for f in image_files if f.with_suffix('.webp').exists() and f.exists()]
    if files_to_move:
        move_task_id = progress.add_task("[yellow]正在归档原图...", total=len(files_to_move))
        with progress:
            move_originals(src_dir, backup_dir, files_to_move, progress, move_task_id, is_single_file=is_single_file)

    logging.info(f"=== 任务结束: {datetime.datetime.now()} ===")
    console.print(f"\n[bold green]✅ 任务全部完成！日志已存至源目录 logs 文件夹。[/bold green]")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[bold red]已手动中断任务。[/bold red]")
    except Exception as e:
        console.print(f"\n[bold red]发生致命错误: {e}[/bold red]")
