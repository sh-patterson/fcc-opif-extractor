from fcc_ad_tracker.extract import (
    ExtractionResult,
    extract_pdf_text,
    extract_text_pages,
    has_text_layer,
)


def test_has_text_layer_true(text_pdf):
    assert has_text_layer(text_pdf) is True


def test_has_text_layer_false(empty_text_pdf):
    assert has_text_layer(empty_text_pdf) is False


def test_extract_text_pages(text_pdf):
    pages = extract_text_pages(text_pdf)
    assert len(pages) == 1
    text = pages[0]
    assert "ACME PAC" in text
    assert "Jane Smith" in text
    assert "$15,000.00" in text


def test_extract_pdf_text_with_text_layer(text_pdf):
    result = extract_pdf_text(text_pdf)
    assert result.has_text is True
    assert result.ocr_used is False
    assert len(result.pages) == 1
    assert "ACME PAC" in result.pages[0]
    assert result.error is None


def test_extract_pdf_text_empty_no_ocr(empty_text_pdf):
    result = extract_pdf_text(empty_text_pdf)
    # Empty PDF with no OCR available should still return a result
    assert isinstance(result, ExtractionResult)
    # If OCR isn't available, has_text should be False
    if not result.ocr_used:
        assert result.has_text is False
