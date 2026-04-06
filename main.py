import os
import subprocess
import shutil
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
import argparse

console = Console()

def get_cwebp_path() -> str:
    # 优先使用项目内的 bin/cwebp.exe，方便打包发布
    local_cwebp = Path(__file__).resolve().parent / "bin" / "cwebp.exe"
    if local_cwebp.exists():
        return str(local_cwebp)
    return "cwebp"

def get_cwebp_cmd(input_file: Path, output_file: Path) -> list[str]:
    return [
        get_cwebp_path(),
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
    
    # 鲁棒性：支持中断后恢复
    if output_file.exists() and output_file.stat().st_size > 0:
        return {'status': 'skipped', 'input': input_file, 'output': output_file, 'error': None}

    cmd = get_cwebp_cmd(input_file, output_file)
    
    try:
        # 使用 subprocess，监控 stderr 捕获错误
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if result.returncode != 0:
            if output_file.exists():
                output_file.unlink()
            return {'status': 'error', 'input': input_file, 'output': output_file, 'error': result.stderr}
        
        orig_size = input_file.stat().st_size
        new_size = output_file.stat().st_size
        return {'status': 'success', 'input': input_file, 'output': output_file, 'error': None, 'orig_size': orig_size, 'new_size': new_size}
        
    except Exception as e:
        if output_file.exists():
            output_file.unlink()
        return {'status': 'error', 'input': input_file, 'output': output_file, 'error': str(e)}

def move_originals(src_dir: Path, backup_dir: Path, image_files: list[Path]):
    console.print("\n[bold cyan]开始移动原始图片文件到备份目录...[/bold cyan]")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
    ) as progress:
        task = progress.add_task("Moving...", total=len(image_files))
        
        for img_file in image_files:
            try:
                rel_path = img_file.relative_to(src_dir)
            except ValueError:
                progress.update(task, advance=1)
                continue
            
            dest_file = backup_dir / rel_path
            
            # 创建目标目录结构
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            
            try:
                if dest_file.exists():
                    dest_file.unlink()
                shutil.move(str(img_file), str(dest_file))
            except Exception as e:
                console.print(f"[red]移动文件失败 {img_file}: {e}[/red]")
            
            progress.update(task, advance=1)

def main():
    parser = argparse.ArgumentParser(description="二次元插画高保真批量压缩工具 (WebP 方案)")
    parser.add_argument("-s", "--src", help="源目录路径 (包含图片文件)")
    parser.add_argument("-b", "--backup", help="原始图片文件备份目录路径")
    parser.add_argument("-w", "--workers", type=int, default=os.cpu_count(), help="并行工作进程数 (默认: CPU核心数)")
    args = parser.parse_args()

    # --- 交互式引导模式 ---
    if not args.src or not args.backup:
        console.print("[bold magenta]==================================================[/bold magenta]")
        console.print("[bold white]   WebP-Forge: 二次元插画高保真批量压缩工具[/bold white]")
        console.print("[bold magenta]==================================================[/bold magenta]\n")
        
        console.print("[cyan]欢迎使用！本工具将帮助您批量将图片压缩为 WebP 格式，并保留极致细节。[/cyan]")
        console.print("[yellow]提示：直接拖拽文件夹到本窗口即可自动输入路径。\n[/yellow]")

        if not args.src:
            while True:
                src_input = console.input("[bold green]步骤 1: 请输入/拖入需要压缩的【源图片文件夹】路径: [/bold green]").strip().strip('"')
                src_dir = Path(src_input).resolve()
                if src_dir.is_dir():
                    break
                console.print(f"[bold red]错误: 路径不存在或不是文件夹，请重新输入。[/bold red]")
        else:
            src_dir = Path(args.src).resolve()

        if not args.backup:
            while True:
                backup_input = console.input("[bold green]步骤 2: 请输入/拖入用于存放原始文件的【备份文件夹】路径: [/bold green]").strip().strip('"')
                backup_dir = Path(backup_input).resolve()
                # 允许创建备份目录
                try:
                    backup_dir.mkdir(parents=True, exist_ok=True)
                    break
                except Exception as e:
                    console.print(f"[bold red]错误: 无法创建或访问该目录: {e}[/bold red]")
        else:
            backup_dir = Path(args.backup).resolve()
        
        # 确认信息
        console.print(f"\n[bold blue]任务确认:[/bold blue]")
        console.print(f"  - 源目录: {src_dir}")
        console.print(f"  - 备份目录: {backup_dir}")
        console.print(f"  - 并发核心: {args.workers}")
        
        confirm = console.input("\n[bold yellow]确认开始执行吗？(Y/N): [/bold yellow]").strip().lower()
        if confirm != 'y':
            console.print("[red]任务已取消。[/red]")
            return
    else:
        # 命令行模式
        src_dir = Path(args.src).resolve()
        backup_dir = Path(args.backup).resolve()

    if not src_dir.is_dir():
        console.print(f"[bold red]错误: 源目录不存在或不是一个目录 -> {src_dir}[/bold red]")
        return

    console.print(f"[bold green]源目录:[/bold green] {src_dir}")
    console.print(f"[bold green]备份目录:[/bold green] {backup_dir}")
    console.print(f"[bold green]工作进程数:[/bold green] {args.workers}")

    # 1. 扫描文件
    console.print("\n[bold cyan]正在扫描图片文件...[/bold cyan]")
    
    # 定义支持的常见图片格式（自动排除 .webp）
    image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif'}
    image_files = [f for f in src_dir.rglob("*") if f.is_file() and f.suffix.lower() in image_extensions]
    
    if not image_files:
        console.print("[yellow]未找到任何支持的图片文件。[/yellow]")
        return
        
    console.print(f"共找到 [bold yellow]{len(image_files)}[/bold yellow] 个图片文件。")

    # 2. 批量压缩
    console.print("\n[bold cyan]开始批量压缩...[/bold cyan]")
    
    success_count = 0
    skipped_count = 0
    error_count = 0
    total_orig_size = 0
    total_new_size = 0
    errors = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("({task.completed}/{task.total})"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
    ) as progress:
        task = progress.add_task("Compressing...", total=len(image_files))
        
        # 利用多进程，绕过 GIL，满载利用多核 CPU 性能
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            future_to_file = {executor.submit(worker, f): f for f in image_files}
            
            for future in as_completed(future_to_file):
                res = future.result()
                
                if res['status'] == 'success':
                    success_count += 1
                    total_orig_size += res['orig_size']
                    total_new_size += res['new_size']
                elif res['status'] == 'skipped':
                    skipped_count += 1
                elif res['status'] == 'error':
                    error_count += 1
                    errors.append((res['input'], res['error']))
                
                progress.update(task, advance=1)

    # 3. 结果统计
    console.print("\n[bold cyan]压缩任务完成统计:[/bold cyan]")
    console.print(f"成功: [green]{success_count}[/green] | 跳过 (已存在): [yellow]{skipped_count}[/yellow] | 失败: [red]{error_count}[/red]")
    
    if success_count > 0:
        saved_size = total_orig_size - total_new_size
        save_ratio = (saved_size / total_orig_size) * 100 if total_orig_size > 0 else 0
        console.print(f"原总体积 (新增): {total_orig_size / (1024*1024):.2f} MB")
        console.print(f"现总体积 (新增): {total_new_size / (1024*1024):.2f} MB")
        console.print(f"节省空间 (新增): [bold green]{saved_size / (1024*1024):.2f} MB ({save_ratio:.2f}%)[/bold green]")

    if errors:
        console.print("\n[bold red]错误日志 (前10个):[/bold red]")
        for filepath, err in errors[:10]:
            console.print(f"文件: {filepath}\n错误: {err.strip()}\n")

    # 4. 移动原始文件
    files_to_move = [f for f in image_files if f.with_suffix('.webp').exists() and f.exists()]
    if files_to_move:
        if error_count > 0:
            console.print("\n[bold yellow]警告: 存在部分压缩失败的文件，但这不影响已成功文件的移动。[/bold yellow]")
        move_originals(src_dir, backup_dir, files_to_move)
        console.print("\n[bold green]全部流程执行完毕！[/bold green]")
    elif error_count == len(image_files):
         console.print("\n[bold red]全部文件压缩失败，未执行移动操作。请检查是否安装了 cwebp 命令行工具并添加到系统变量。[/bold red]")
    else:
         console.print("\n[bold green]没有需要移动的文件，流程结束。[/bold green]")

if __name__ == "__main__":
    main()