from typing import Any


class ASTUtils:
    """
    Utility class for interacting with the JSON AST format used by the translation engine.
    """

    @staticmethod
    def count_segments(txn: dict[str, Any]) -> int:
        """
        Recursively counts the number of valid EDI segments in a transaction AST dictionary.
        """
        count = 0

        def traverse(node: Any) -> None:
            nonlocal count
            if isinstance(node, dict):
                for k, v in node.items():
                    # Segments are uppercase, 2-3 alphanumeric characters
                    if k.isupper() and 2 <= len(k) <= 3 and k.isalnum():
                        if isinstance(v, list) and len(v) > 0:
                            # Check if the list contains standard segments or if it's a loop
                            first_item = v[0]
                            is_loop = False
                            if isinstance(first_item, dict):
                                for sub_k in first_item:
                                    if sub_k.isupper() and 2 <= len(sub_k) <= 3 and sub_k.isalnum():
                                        is_loop = True
                                        break
                            if is_loop:
                                traverse(v)
                            else:
                                count += len(v)
                        elif isinstance(v, dict):
                            count += 1
                    elif isinstance(v, (dict, list)):
                        traverse(v)
            elif isinstance(node, list):
                for item in node:
                    traverse(item)

        traverse(txn)
        return count
