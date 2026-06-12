from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class PageImage:
    page_number: int
    image_path: Path
    width: int
    height: int
    dpi: int
    reused: bool

    @property
    def page_id(self) -> str:
        return f"page_{self.page_number:03d}"


def render_pdf_pages(
    pdf_path: Path,
    pages_dir: Path,
    dpi: int = 300,
    image_format: str = "png",
    force: bool = False,
) -> list[PageImage]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required to render PDFs. Run: pip install -r requirements.txt"
        ) from exc

    pages_dir.mkdir(parents=True, exist_ok=True)
    image_format = image_format.lower().lstrip(".")
    if image_format != "png":
        raise ValueError("Phase 1 currently writes PNG page images only.")

    rendered: list[PageImage] = []
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    with fitz.open(pdf_path) as document:
        if document.page_count == 0:
            raise ValueError(f"PDF has no pages: {pdf_path}")

        for index, page in enumerate(document, start=1):
            output_path = pages_dir / f"page_{index:03d}.png"
            reused = output_path.exists() and not force

            if not reused:
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                pixmap.save(output_path)
                width = int(pixmap.width)
                height = int(pixmap.height)
            else:
                try:
                    from PIL import Image
                except ImportError as exc:
                    raise RuntimeError(
                        "Pillow is required to inspect cached page images. "
                        "Run: pip install -r requirements.txt"
                    ) from exc
                with Image.open(output_path) as image:
                    width, height = image.size

            rendered.append(
                PageImage(
                    page_number=index,
                    image_path=output_path,
                    width=width,
                    height=height,
                    dpi=dpi,
                    reused=reused,
                )
            )

    manifest_path = pages_dir / "pages_manifest.json"
    manifest_path.write_text(
        json.dumps([_page_to_json(page) for page in rendered], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return rendered


def _page_to_json(page: PageImage) -> dict[str, object]:
    data = asdict(page)
    data["image_path"] = str(page.image_path)
    data["page_id"] = page.page_id
    return data
