from infra_seedwork import StackEnvironment
from infra_seedwork.env import PRODUCTION_STACK_NAME


def test_stack_environment_enum_contract() -> None:
    assert StackEnvironment.PRODUCTION == "production"
    assert StackEnvironment.STAGING == "staging"
    assert set(StackEnvironment) == {StackEnvironment.PRODUCTION, StackEnvironment.STAGING}
    assert PRODUCTION_STACK_NAME == StackEnvironment.PRODUCTION
