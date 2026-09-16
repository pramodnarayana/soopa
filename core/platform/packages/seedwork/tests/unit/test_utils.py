from seedwork.utils import generate_deterministic_id


def test_generate_deterministic_id_is_deterministic() -> None:
    prefix = "tst"
    namespace = "test_namespace"
    name = "test_name"

    id1 = generate_deterministic_id(prefix, namespace, name)
    id2 = generate_deterministic_id(prefix, namespace, name)

    assert id1 == id2
    assert id1.startswith(f"{prefix}_")


def test_generate_deterministic_id_differs_by_namespace() -> None:
    prefix = "tst"
    name = "test_name"

    id1 = generate_deterministic_id(prefix, "namespace_a", name)
    id2 = generate_deterministic_id(prefix, "namespace_b", name)

    assert id1 != id2


def test_generate_deterministic_id_differs_by_name() -> None:
    prefix = "tst"
    namespace = "test_namespace"

    id1 = generate_deterministic_id(prefix, namespace, "name_a")
    id2 = generate_deterministic_id(prefix, namespace, "name_b")

    assert id1 != id2


def test_generate_deterministic_id_differs_by_prefix() -> None:
    namespace = "test_namespace"
    name = "test_name"

    id1 = generate_deterministic_id("tst", namespace, name)
    id2 = generate_deterministic_id("oth", namespace, name)

    assert id1 != id2
