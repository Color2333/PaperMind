from __future__ import annotations

from pathlib import Path


class VisionPdfReader:
    """
    Vision-first placeholder:
    - Current implementation returns pseudo page descriptors.
    - Can be swapped with real page rendering + multimodal API calls.
    """

    def extract_page_descriptions(self, pdf_path: str, max_pages: int = 8) -> str:
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"pdf not found: {pdf_path}")
        return (
            f"Vision analysis mock for `{path.name}`; "
            f"inspected up to {max_pages} pages; "
            "captured method diagrams, experiment tables and ablation plots."
        )
