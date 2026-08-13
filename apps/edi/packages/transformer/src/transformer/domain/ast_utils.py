from typing import Any


class ASTUtils:
    """
    Utility class for interacting with the JSON AST format used by the translation engine.
    """

    @staticmethod
    def _is_segment_key(k: str) -> bool:
        return k.isupper() and 2 <= len(k) <= 3 and k.isalnum()

    @staticmethod
    def _is_loop_list(v: list[Any]) -> bool:
        if not v:
            return False
        first_item = v[0]
        if isinstance(first_item, dict):
            for sub_k in first_item:
                if ASTUtils._is_segment_key(sub_k):
                    return True
        return False

    @staticmethod
    def _count_segment_node(k: str, v: Any, traverse_fn: Any) -> int:
        if ASTUtils._is_segment_key(k):
            if isinstance(v, list) and len(v) > 0:
                if ASTUtils._is_loop_list(v):
                    traverse_fn(v)
                else:
                    return len(v)
            elif isinstance(v, dict):
                return 1
        elif isinstance(v, (dict, list)):
            traverse_fn(v)
        return 0

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
                    count += ASTUtils._count_segment_node(k, v, traverse)
            elif isinstance(node, list):
                for item in node:
                    traverse(item)

        traverse(txn)
        return count
