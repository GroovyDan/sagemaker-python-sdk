# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
#     http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.
# language governing permissions and limitations under the License.
from __future__ import absolute_import

import pytest

import sagemaker

from mock import (
    Mock,
    PropertyMock,
)

from sagemaker.estimator import Estimator
from sagemaker.workflow.properties import Properties
from sagemaker.workflow.steps import (
    Step,
    StepTypeEnum,
)
from sagemaker.workflow.step_collections import (
    StepCollection,
    RegisterModel,
)

REGION = "us-west-2"
BUCKET = "my-bucket"
IMAGE_URI = "fakeimage"
ROLE = "DummyRole"
MODEL_NAME = "gisele"


class CustomStep(Step):
    def __init__(self, name):
        super(CustomStep, self).__init__(name, StepTypeEnum.TRAINING)
        self._properties = Properties(path=f"Steps.{name}")

    @property
    def arguments(self):
        return dict()

    @property
    def properties(self):
        return self._properties


@pytest.fixture
def boto_session():
    role_mock = Mock()
    type(role_mock).arn = PropertyMock(return_value=ROLE)

    resource_mock = Mock()
    resource_mock.Role.return_value = role_mock

    session_mock = Mock(region_name=REGION)
    session_mock.resource.return_value = resource_mock

    return session_mock


@pytest.fixture
def client():
    """Mock client.

    Considerations when appropriate:

        * utilize botocore.stub.Stubber
        * separate runtime client from client
    """
    client_mock = Mock()
    client_mock._client_config.user_agent = (
        "Boto3/1.14.24 Python/3.8.5 Linux/5.4.0-42-generic Botocore/1.17.24 Resource"
    )
    return client_mock


@pytest.fixture
def sagemaker_session(boto_session, client):
    return sagemaker.session.Session(
        boto_session=boto_session,
        sagemaker_client=client,
        sagemaker_runtime_client=client,
        default_bucket=BUCKET,
    )


@pytest.fixture
def estimator(sagemaker_session):
    return Estimator(
        image_uri=IMAGE_URI,
        role=ROLE,
        instance_count=1,
        instance_type="c4.4xlarge",
        sagemaker_session=sagemaker_session,
    )


def test_step_collection():
    step_collection = StepCollection(steps=[CustomStep("MyStep1"), CustomStep("MyStep2")])
    assert step_collection.request_dicts() == [
        {"Name": "MyStep1", "Type": "Training", "Arguments": dict()},
        {"Name": "MyStep2", "Type": "Training", "Arguments": dict()},
    ]


def test_register_model(estimator):
    model_data = f"s3://{BUCKET}/model.tar.gz"
    register_model = RegisterModel(
        name="RegisterModelStep",
        estimator=estimator,
        model_data=model_data,
        content_types=["content_type"],
        response_types=["response_type"],
        inference_instances=["inference_instance"],
        transform_instances=["transform_instance"],
    )
    assert register_model.request_dicts() == [
        {
            "Name": "RegisterModelStep",
            "Type": "RegisterModel",
            "Arguments": {
                "InferenceSpecification": {
                    "Containers": [
                        {"Image": "fakeimage", "ModelDataUrl": "s3://my-bucket/model.tar.gz"}
                    ],
                    "SupportedContentTypes": ["content_type"],
                    "SupportedRealtimeInferenceInstanceTypes": ["inference_instance"],
                    "SupportedResponseMIMETypes": ["response_type"],
                    "SupportedTransformInstanceTypes": ["transform_instance"],
                },
            },
        },
    ]
