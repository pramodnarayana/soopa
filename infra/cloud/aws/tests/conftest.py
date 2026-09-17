import pulumi
import pytest


class MyMocks(pulumi.runtime.Mocks):
    def new_resource(self, args: pulumi.runtime.MockResourceArgs):
        # Simply return a mock ID and the same inputs as outputs
        return [f"{args.name}-id", args.inputs]

    def call(self, args: pulumi.runtime.MockCallArgs):
        # Mock any invoke calls (e.g. aws.get_caller_identity)
        if args.token == "aws:index/getCallerIdentity:getCallerIdentity":
            return {
                "accountId": "123456789012",
                "arn": "arn:aws:iam::123456789012:root",
                "userId": "AKIAIOSFODNN7EXAMPLE",
            }
        if args.token == "aws:index/getRegion:getRegion":
            return {"name": "us-east-1"}
        return {}


@pytest.fixture(scope="function", autouse=True)
def setup_pulumi_mocks():
    pulumi.runtime.set_mocks(MyMocks())
