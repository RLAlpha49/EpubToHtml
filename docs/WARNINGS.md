# Warning Codes Reference

Conversion warnings are non-fatal diagnostics. They describe content that was skipped,
references that could not be resolved, and encoding fallbacks. Use `--fail-on-warning`
to prevent publication when any warning occurs, or `--report-json` to capture the full
list for automation.

---

## Image Warnings

### `skipped-image`

An image item was skipped during processing. Common causes:

- The image format is not supported (e.g., SVG in safe mode).
- The image exceeds the `max_entry_bytes` limit.
- The image is inside a skipped document.
- Safe mode: the image failed raster signature validation.

### `ambiguous-image`

An image reference could not be resolved because multiple images share the same
basename in different directories. The converter does not guess which one was intended.

**Example:** Two images `chapter1/photo.jpg` and `chapter2/photo.jpg` both referenced as
`photo.jpg`.

### `unresolved-image`

An image reference could not be resolved in the image index. The referenced path does
not match any registered image.

**Example:** An EPUB references `images/missing.png` but the manifest does not include
that file.

### `preserved-resource-reference`

A local resource reference (e.g., to a video or audio file) was preserved in the output
because the resource was not extracted. The reference will not work in the single-file
output.

---

## Document Warnings

### `skipped-document`

A document item was skipped during conversion. Common causes:

- The document is an EPUB navigation document (`nav.xhtml`) and `navigation` is in
  `--exclude-content`.
- The document is outside the `--spine-range`.
- The document is a cover page and `--remove-cover` is set.

### `decode-fallback`

UTF-8 decoding of a document failed, and automatic encoding detection (via `chardet`)
could not determine the encoding with sufficient confidence. The document was decoded
using `latin-1` as a fallback, which may produce garbled text for non-Latin content.

**Action:** Verify the source EPUB's encoding declaration. If the output has garbled
characters, this warning is the likely cause.

---

## Stylesheet Warnings

### `skipped-stylesheet`

A stylesheet item was skipped. Common causes:

- Safe mode is enabled (EPUB-originated CSS is removed).
- `--preserve-internal-css` is not set.

---

## Resource Warnings

### `skipped-resource`

A non-document, non-image resource (audio, video, font) was skipped because the
corresponding policy (`--media-policy`, `--font-policy`) is set to `omit`.

### `omitted-resource`

A resource reference was omitted from the output. The resource exists in the EPUB
but was not included due to the active policy.

---

## Encoding Warnings

### `decode-fallback` (Encoding)

See [Document Warnings](#document-warnings) above.

---

## Safe Mode Warnings

### `unsafe-content-removed`

Active content (script elements, event handlers, `javascript:` URLs, `data:` URLs
with non-image MIME types) was removed during safe-mode processing.

---

## Warning Codes Summary

| Code | Category | Description |
| --- | --- | --- |
| `skipped-image` | Image | Image item skipped during processing |
| `ambiguous-image` | Image | Multiple images share the same basename |
| `unresolved-image` | Image | Image reference not found in index |
| `preserved-resource-reference` | Image | Local resource reference preserved in output |
| `skipped-document` | Document | Document item skipped during conversion |
| `decode-fallback` | Document | Latin-1 fallback used for decoding |
| `skipped-stylesheet` | Stylesheet | Stylesheet skipped |
| `skipped-resource` | Resource | Resource skipped due to policy |
| `omitted-resource` | Resource | Resource reference omitted from output |
| `unsafe-content-removed` | Safe mode | Active content removed during sanitization |
