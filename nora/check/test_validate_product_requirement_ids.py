import unittest

from nora.check.validate_product_requirement_ids import validate_documents


class ValidateProductRequirementIdsTests(unittest.TestCase):
    def setUp(self):
        self.inventory = """1. [EDU requirements (EDU-01 – EDU-02)](#edu)
2. [Cross requirements (CROSS-01 – CROSS-01)](#cross)
---
### EDU-01 — One
### EDU-02 — Two
### CROSS-01 — Three
"""
        self.matrix = """| EDU-01 | requirement |
| EDU-02 | requirement |
| CROSS-01 | requirement |
"""
        self.required_ids = {"EDU-01", "EDU-02", "CROSS-01"}

    def test_accepts_matching_documents_and_ranges(self):
        self.assertEqual(
            validate_documents(self.inventory, self.matrix, self.required_ids),
            [],
        )

    def test_reports_duplicate_and_missing_ids(self):
        matrix = self.matrix + "| EDU-01 | duplicate |\n"
        errors = validate_documents(self.inventory, matrix, self.required_ids)
        self.assertTrue(any("duplicate requirement IDs" in error for error in errors))

    def test_reports_unexpected_ids(self):
        matrix = self.matrix + "| EDU-03 | unexpected |\n"
        errors = validate_documents(self.inventory, matrix, self.required_ids)
        self.assertTrue(any("unexpected requirement IDs" in error for error in errors))

    def test_reports_stale_toc_range(self):
        inventory = self.inventory.replace("EDU-01 – EDU-02", "EDU-01 – EDU-01")
        errors = validate_documents(inventory, self.matrix, self.required_ids)
        self.assertTrue(any("TOC range for EDU" in error for error in errors))

    def test_reports_document_set_mismatch(self):
        matrix = self.matrix.replace("| EDU-02 | requirement |\n", "")
        errors = validate_documents(self.inventory, matrix, self.required_ids)
        self.assertTrue(any("matrix is missing requirement IDs" in error for error in errors))
        self.assertTrue(any("ID sets differ" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
