import csv


def selected_pdfs(root, files):
    catalogue = root / "metadata.csv"
    if not catalogue.exists():
        return dict.fromkeys(files, {})
    with catalogue.open(encoding="utf-8-sig", newline="") as stream:
        entries = [row for row in csv.DictReader(stream)
                   if row["include_in_index"].strip().lower() == "true"]
    selected = {row["file_path"]: row for row in entries}
    if len(selected) != len(entries) or selected.keys() - files.keys():
        raise ValueError("The catalogue has duplicate paths or is missing selected PDFs.")
    return selected
