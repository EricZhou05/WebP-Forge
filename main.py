import os
import subprocess
import shutil
import logging
import datetime
import argparse
import sys
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from PIL import Image

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

def setup_file_logging(log_dir: Path):
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"compress_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    formatter = logging.Formatter("%(message)s")
    file_handler.setFormatter(formatter)
    logging.getLogger().addHandler(file_handler)
    
    return file_handler, log_file

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

def worker(input_file: Path, rename_mode: bool = False) -> dict:
    # 获取原始文件的修改时间和访问时间
    orig_stat = input_file.stat()
    orig_mtime = orig_stat.st_mtime
    orig_atime = orig_stat.st_atime
    
    if rename_mode:
        # 格式 YYYY_MM_DD_原始文件名
        date_prefix = datetime.datetime.fromtimestamp(orig_mtime).strftime('%Y_%m_%d')
        output_file = input_file.parent / f"{date_prefix}_{input_file.stem}.webp"
    else:
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
        
        # 压缩成功后，同步修改时间
        os.utime(output_file, (orig_atime, orig_mtime))
        
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

def restore_worker(input_file: Path) -> dict:
    output_file = input_file.with_suffix('.png')
    
    if output_file.exists() and output_file.stat().st_size > 0:
        return {'status': 'skipped', 'input': input_file, 'output': output_file}

    try:
        # 使用 Pillow 无损还原 WebP 到 PNG
        with Image.open(input_file) as img:
            img.save(output_file, "PNG")
        
        orig_size = input_file.stat().st_size
        new_size = output_file.stat().st_size
        return {
            'status': 'success', 
            'input': input_file, 
            'output': output_file, 
            'orig_size': orig_size, 
            'new_size': new_size,
            'cmd': "PIL.Image.save (PNG)"
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
    parser = argparse.ArgumentParser(description="二次元插画高保真批量压缩/还原工具")
    parser.add_argument("-s", "--src", help="源目录或文件")
    parser.add_argument("-b", "--backup", help="备份目录")
    parser.add_argument("-w", "--workers", type=int, default=max(1, os.cpu_count() - 1))
    parser.add_argument("-m", "--mode", choices=["compress", "compress_rename", "restore"], help="操作模式: compress (压缩), compress_rename (压缩并重命名), restore (还原)")
    args = parser.parse_args()

    # 初始化全局控制台日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)]
    )

    console.print(Panel.fit("[bold magenta]WebP-Forge 极致压缩/还原工具[/bold magenta]\n[cyan]高保真 / 多核并行 / 自动备份[/cyan]", border_style="magenta"))

    if not args.mode:
        console.print("[bold green]可选模式:[/bold green]")
        console.print("  [1] 极致压缩 (默认模式，直接输入路径即可)")
        console.print("  [2] 压缩且重命名 (日期前缀 + 保留原始修改时间)")
        console.print("  [3] 无损还原 (WebP -> PNG)")
        
        src_input = console.input("\n[bold green]请输入待处理的路径 (或输入 2 / 3 切换模式): [/bold green]").strip().strip("\"")
        
        mode = "compress"
        if src_input == "2":
            mode = "compress_rename"
            src_input = console.input("[bold green]请输入待处理的路径 (模式二: 压缩且重命名): [/bold green]").strip().strip("\"")
        elif src_input == "3":
            mode = "restore"
            src_input = console.input("[bold green]请输入待处理的路径 (模式三: 无损还原): [/bold green]").strip().strip("\"")
        elif src_input == "1":
            mode = "compress"
            src_input = console.input("[bold green]请输入待处理的路径 (模式一: 极致压缩): [/bold green]").strip().strip("\"")
            
        if not src_input:
            console.print("[bold red]错误: 路径不能为空[/bold red]")
            return
        src_path = Path(src_input).resolve()
    else:
        mode = args.mode
        if not args.src:
            console.print("[bold red]错误: 命令行模式下未指定源路径 --src[/bold red]")
            return
        src_path = Path(args.src).resolve()

    if not src_path.exists():
        console.print(f"[bold red]错误: 路径不存在 {src_path}[/bold red]")
        return

    is_single_file = src_path.is_file()
    if mode.startswith("compress"):
        image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif'}
    else:
        image_extensions = {'.webp'}

    # 扫描任务，拆分为独立的文件夹任务
    if is_single_file:
        if src_path.suffix.lower() not in image_extensions:
            console.print(f"[bold red]错误: 不支持的文件格式 {src_path.suffix}[/bold red]")
            return
        tasks = {src_path.parent: [src_path]}
    else:
        tasks = {}
        with console.status("[bold yellow]正在扫描图片资源...", spinner="bouncingBall"):
            for root, dirs, files in os.walk(src_path):
                root_path = Path(root)
                img_files = [root_path / f for f in files if (root_path / f).suffix.lower() in image_extensions]
                if img_files:
                    tasks[root_path] = img_files

    if not tasks:
        console.print("[yellow]未找到待处理的图片格式。[/yellow]")
        return

    console.print(f"\n[bold cyan]扫描完毕，共发现 {len(tasks)} 个任务 (包含图片的文件夹):[/bold cyan]")
    for idx, (dir_path, files) in enumerate(tasks.items(), 1):
        console.print(f"  任务 {idx}: {dir_path} ({len(files)} 张图片)")
    console.print("")

    workers = args.workers

    global_success = 0
    global_error = 0
    global_skipped = 0
    global_orig_size = 0
    global_new_size = 0

    for idx, (task_dir, image_files) in enumerate(tasks.items(), 1):
        console.print(f"\n[bold magenta]--- 正在处理任务 {idx}/{len(tasks)}: {task_dir} ---[/bold magenta]")
        
        if is_single_file:
            backup_dir = task_dir
        else:
            if not args.backup:
                backup_dir = task_dir.parent / f"{task_dir.name}_forge"
            else:
                base_backup = Path(args.backup).resolve()
                rel_path = task_dir.relative_to(src_path)
                backup_dir = base_backup / rel_path

        # 设置分目录的日志文件
        file_handler, log_file_path = setup_file_logging(task_dir / "logs")
        
        logging.info(f"=== 任务 {idx} 启动: {datetime.datetime.now()} ===")
        logging.info(f"任务路径: {task_dir}")
        logging.info(f"模式: {mode}")
        if not is_single_file:
            logging.info(f"备份路径: {backup_dir}")
        logging.info(f"待处理: {len(image_files)} 张")

        success_count = 0
        skipped_count = 0
        error_count = 0
        task_orig_size = 0
        task_new_size = 0
        successful_inputs = []

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
            task_desc = f"[white]任务 {idx} 压缩中..." if mode.startswith("compress") else f"[white]任务 {idx} 还原中..."
            process_task = progress.add_task(task_desc, total=len(image_files))
            
            from functools import partial
            with ProcessPoolExecutor(max_workers=workers) as executor:
                if mode.startswith("compress"):
                    rename_flag = (mode == "compress_rename")
                    target_worker = partial(worker, rename_mode=rename_flag)
                else:
                    target_worker = restore_worker
                    
                future_to_file = {executor.submit(target_worker, f): f for f in image_files}
                
                for future in as_completed(future_to_file):
                    res = future.result()
                    if res['status'] == 'success':
                        success_count += 1
                        task_orig_size += res['orig_size']
                        task_new_size += res['new_size']
                        successful_inputs.append(res['input'])
                        logging.info(f"[SUCCESS] {res['input'].name} -> {res['output'].name}")
                    elif res['status'] == 'skipped':
                        skipped_count += 1
                        logging.info(f"[SKIP] {res['input'].name} 的对应文件已存在。")
                    elif res['status'] == 'error':
                        error_count += 1
                        logging.error(f"[ERROR] {res['input'].name} -> {res['error']}")
                    
                    progress.update(process_task, advance=1)

            if successful_inputs:
                move_task_id = progress.add_task(f"[yellow]任务 {idx} 归档原图...", total=len(successful_inputs))
                move_originals(task_dir, backup_dir, successful_inputs, progress, move_task_id, is_single_file=is_single_file)

        logging.info(f"=== 任务 {idx} 结束: {datetime.datetime.now()} ===")
        
        logging.getLogger().removeHandler(file_handler)
        file_handler.close()
        
        global_success += success_count
        global_error += error_count
        global_skipped += skipped_count
        global_orig_size += task_orig_size
        global_new_size += task_new_size

    summary_title = "📊 本次所有任务总结"
    table = Table(title=summary_title, box=None, show_header=False)
    table.add_column("Key", style="bold cyan")
    table.add_column("Value")
    
    table.add_row("成功完成", f"[green]{global_success}[/green] 张")
    table.add_row("已跳过", f"[yellow]{global_skipped}[/yellow] 张")
    table.add_row("错误失败", f"[red]{global_error}[/red] 张")
    
    if global_success > 0:
        if mode.startswith("compress"):
            reduction = global_orig_size - global_new_size
            reduction_percent = (reduction / global_orig_size) * 100 if global_orig_size > 0 else 0
            table.add_row("原始总体积", f"{global_orig_size / (1024*1024):.2f} MB")
            table.add_row("压缩后体积", f"{global_new_size / (1024*1024):.2f} MB")
            table.add_row("空间缩减率", f"[bold green]{reduction_percent:.1f}%[/bold green] (节省 {reduction / (1024*1024):.2f} MB)")
        else:
            table.add_row("WebP 总体积", f"{global_orig_size / (1024*1024):.2f} MB")
            table.add_row("还原后体积", f"{global_new_size / (1024*1024):.2f} MB")

    console.print("\n", table)
    console.print(f"\n[bold green]✅ 所有任务全部完成！分项日志已存至各自目录的 logs 文件夹。[/bold green]")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[bold red]已手动中断任务。[/bold red]")
    except Exception as e:
        console.print(f"\n[bold red]发生致命错误: {e}[/bold red]")
