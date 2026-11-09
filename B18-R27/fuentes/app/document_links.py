"""Explicit source-scoped links to registered documentary originals."""

REAL_V1_SHA = "d06dccd3a6d6499abcee55bd818705d77007eaf2865abd0c675206fc00822370"
DOCUMENT_LINKS = {
    "IF-2026-82616470-APN-DCS_IOSFA-1.pdf":
        "73e19e6c0840606ef8b8da5ccb2d20c43d4bf3a4d22943756a0c4eab5169f9fd",
    "NBU-Version-2012-Act.-2016(1).pdf":
        "6d2837c6a54d3e7f7e0b0cd69de9051da532ae5685dcc78e3c0a243ec08cdc07",
    "Anexo-11.2023-NBU-2012-16-Final.pdf":
        "e9f987ab2820b58c95c36be9e085572996b04484688e83ff91976abdf1162607",
    "Anexo-01.2024-NBU-2012.pdf":
        "3093b0b84887631d871d07743782a35a2385406ec9b691e6fe94908b942ead68",
}


def _document(name: object, source_sha256: str, documents: list[dict],
              category: str) -> dict:
    if not isinstance(name, str) or not name:
        return {"status": "source_document_not_named", "catalogue_name": name}
    expected = DOCUMENT_LINKS.get(name) if source_sha256 == REAL_V1_SHA else None
    matches = [doc for doc in documents if doc["sha256"] == expected and
               doc["category"] == category] if expected else [
        doc for doc in documents if doc["original_name"] == name and
        doc["category"] == category]
    if not matches:
        return {"status": "registered_document_not_linked", "catalogue_name": name}
    if len(matches) != 1:
        return {"status": "registered_document_ambiguous", "catalogue_name": name}
    doc = matches[0]
    return {"status": "registered", "catalogue_name": name,
            "document_id": doc["id"], "sha256": doc["sha256"],
            "source_match": doc["source_match"],
            "link_basis": ("catalog_hash" if doc["source_match"] == "catalog_hash_match"
                           else "edition_alias_reviewed" if expected else "filename_only")}

