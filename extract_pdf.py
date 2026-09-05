"""将 PDF 文本提取到指定文件，避免把本机路径写入项目。"""

import argparse
from pathlib import Path

def extract_pdf_text(input_path: Path, output_path: Path) -> int:
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError as exc:
        raise SystemExit("缺少 pypdf，请先运行：python -m pip install -r requirements.txt") from exc

    reader = PdfReader(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output:
        for page_number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            output.write(f"\n===== PAGE {page_number} =====\n{text}\n")
    return len(reader.pages)


def main() -> None:
    parser = argparse.ArgumentParser(description="提取 PDF 文本")
    parser.add_argument("--input", required=True, type=Path, help="输入 PDF 路径")
    parser.add_argument("--output", required=True, type=Path, help="输出文本路径")
    args = parser.parse_args()
    pages = extract_pdf_text(args.input, args.output)
    print(f"已提取 {pages} 页：{args.output}")


if __name__ == "__main__":
    main()
