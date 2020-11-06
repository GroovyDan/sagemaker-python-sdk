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
"""The Pipeline entity for workflow."""
from __future__ import absolute_import

import json

from copy import deepcopy
from typing import Any, Dict, List, Sequence, Union

import attr
import botocore

from botocore.exceptions import ClientError

from sagemaker.session import Session
from sagemaker.workflow.entities import (
    Entity,
    Expression,
    RequestType,
)
from sagemaker.workflow.parameters import Parameter
from sagemaker.workflow.properties import Properties
from sagemaker.workflow.steps import Step
from sagemaker.workflow.step_collections import StepCollection
from sagemaker.workflow.utilities import list_to_request


@attr.s
class Pipeline(Entity):
    """Pipeline class for workflow.

    Attributes:
        name (str): The name of the pipeline.
        parameters (Sequence[Parameters]): The list of the parameters.
        steps (Sequence[Steps]): The list of the non-conditional steps associated with the pipeline.
            Of particular note, the workflow service will reject any pipeline definitions that
            specify a step in the list of steps of a pipeline and that step in the `if_steps` or
            `else_steps` of any `ConditionStep`. In particular, any steps that are within the
            `if_steps` or `else_steps` of a `ConditionStep` cannot be listed in the steps of a
            pipeline.

    """

    name: str = attr.ib(factory=str)
    parameters: Sequence[Parameter] = attr.ib(factory=list)
    steps: Sequence[Union[Step, StepCollection]] = attr.ib(factory=list)
    sagemaker_session: Session = attr.ib(default=Session)

    _version: str = "2020-12-01"
    _metadata: Dict[str, Any] = dict()

    def to_request(self) -> RequestType:
        """Gets the request structure for workflow service calls."""
        return {
            "Version": self._version,
            "Metadata": self._metadata,
            "Parameters": list_to_request(self.parameters),
            "Steps": list_to_request(self.steps),
        }

    def create(
        self,
        role_arn: str,
        description: str = None,
        experiment_name: str = None,
        tags: List[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Creates a Pipeline in the Pipelines service.

        Args:
            role_arn (str): Role arn that is assumed by workflow to create step artifacts.
            pipeline_description (str): Description of the pipeline.
            experiment_name (str): Name of the experiment.
            tags (List[Dict[str, str]]): List of {"Key": "string", "Value": "string"} dicts as tags

        Returns:
            response dict from service
        """
        kwargs = self._create_args(role_arn, description)
        update_args(
            kwargs,
            ExperimentName=experiment_name,
            Tags=tags,
        )
        return self.sagemaker_session.sagemaker_client.create_pipeline(**kwargs)

    def _create_args(self, role_arn: str, description: str):
        """Constructs the keyword argument dict for a create_pipeline call.

        Args:
            role_arn (str): Role arn that is assumed by pipelines to create step artifacts.
            pipeline_description (str): Description of the pipeline.

        Returns:
            keyword argument dict for calling create_pipeline.
        """
        kwargs = dict(
            PipelineName=self.name,
            PipelineDefinition=self.definition(),
            RoleArn=role_arn,
        )
        update_args(
            kwargs,
            PipelineDescription=description,
        )
        return kwargs

    def describe(self) -> Dict[str, Any]:
        """Describes a Pipeline in the Workflow service.

        Returns:
            Response dict from service.
        """
        return self.sagemaker_session.sagemaker_client.describe_pipeline(PipelineName=self.name)

    def update(self, role_arn: str, description: str = None) -> Dict[str, Any]:
        """Updates a Pipeline in the Workflow service.

        Args:
            role_arn (str): Role arn that is assumed by workflow to create step artifacts.
            description (str): Description of the pipeline.

        Returns:
            Response dict from service.
        """
        kwargs = self._create_args(role_arn, description)
        return self.sagemaker_session.sagemaker_client.update_pipeline(**kwargs)

    def upsert(
        self,
        role_arn: str,
        description: str = None,
        experiment_name: str = None,
        tags: List[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Creates a pipeline or updates it, if it exists.

        Args:
            role_arn (str): Role arn that is assumed by workflow to create step artifacts.
            pipeline_description (str): Description of the pipeline.
            experiment_name (str): Name of the experiment.
            tags (List[Dict[str, str]]): List of {"Key": "string", "Value": "string"} dicts as tags

        Returns:
            response dict from service
        """
        try:
            response = self.create(role_arn, description, experiment_name, tags)
        except ClientError as e:
            error = e.response["Error"]
            if (
                error["Code"] == "ValidationException"
                and "Pipeline names must be unique within" in error["Message"]
            ):
                response = self.update(role_arn, description)
            else:
                raise
        return response

    def delete(self) -> Dict[str, Any]:
        """Deletes a Pipeline in the Workflow service.

        Returns:
            Response dict from service.
        """
        return self.sagemaker_session.sagemaker_client.delete_pipeline(PipelineName=self.name)

    def start(
        self,
        parameters: Dict[str, Any] = None,
        execution_description: str = None,
    ) -> Dict[str, Any]:
        """Starts a Pipeline execution in the Workflow service.

        Args:
            parameters (List[Dict[str, str]]): List of parameter dicts of the form
                {"Name": "string", "Value": "string"} dicts.
            execution_description (str): Description of the execution.

        Returns:
            Response dict from service.
        """
        exists = True
        try:
            self.describe()
        except ClientError:
            exists = False

        if not exists:
            raise ValueError(
                "This pipeline is not associated with a Pipeline in SageMaker. "
                "Please invoke create() first before attempting to invoke start()."
            )
        kwargs = dict(PipelineName=self.name)
        update_args(
            kwargs,
            PipelineParameters=format_start_parameters(parameters),
            PipelineExecutionDescription=execution_description,
        )
        response = self.sagemaker_session.sagemaker_client.start_pipeline_execution(**kwargs)
        return _PipelineExecution(
            arn=response["PipelineExecutionArn"],
            sagemaker_session=self.sagemaker_session,
        )

    def definition(self) -> str:
        """Converts request structure to string representation for workflow service calls."""
        request_dict = self.to_request()
        request_dict["Steps"] = interpolate(request_dict["Steps"])

        return json.dumps(request_dict)


def format_start_parameters(parameters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Formats start parameter overrides as a list of dicts.

    This list of dicts adheres to the request schema of:

        `{"Name": "MyParameterName", "Value": "MyValue"}`

    Args:
        parameters (Dict[str, Any]): dict of named values where the keys are
            the names of the parameters to pass values into.
    """
    if parameters is None:
        return None
    return [{"Name": name, "Value": str(value)} for name, value in parameters.items()]


def interpolate(request_obj: RequestType) -> RequestType:
    """Replaces Parameter values in list of nested Dict[str, Any] with their workflow expression.

    Args:
        request_obj (RequestType): The request dict.

    Returns:
        RequestType: The request dict with Parameter values replaced by their expression.
    """
    request_obj_copy = deepcopy(request_obj)
    return _interpolate(request_obj_copy)


def _interpolate(obj: Union[RequestType, Any]):
    """Walks the nested request dict, replacing Parameter type values with workflow expressions.

    Args:
        obj (Union[RequestType, Any]): The request dict.
    """
    if isinstance(obj, (Expression, Parameter, Properties)):
        return obj.expr
    if isinstance(obj, dict):
        new = obj.__class__()
        for key, value in obj.items():
            new[key] = interpolate(value)
    elif isinstance(obj, (list, set, tuple)):
        new = obj.__class__(interpolate(value) for value in obj)
    else:
        return obj
    return new


def update_args(args: Dict[str, Any], **kwargs):
    """Updates the request arguments dict with the value if populated

    This is to handle the case that the service API doesn't like NoneTypes for argument values.

    Args:
        request_args (Dict[str, Any]): the request arguments dict
        kwargs: key, value pairs to update the args dict
    """
    for key, value in kwargs.items():
        if value is not None:
            args.update({key: value})


@attr.s
class _PipelineExecution:
    """Internal class for encapsulating pipeline execution instances"""

    arn: str = attr.ib()
    sagemaker_session: Session = attr.ib(default=Session)

    def stop(self):
        """Stops a pipeline execution."""
        return self.sagemaker_session.sagemaker_client.stop_pipeline_execution(
            PipelineExecutionArn=self.arn
        )

    def describe(self):
        """Describes a pipeline execution."""
        return self.sagemaker_session.sagemaker_client.describe_pipeline_execution(
            PipelineExecutionArn=self.arn
        )

    def list_steps(self):
        """Describes a pipeline execution's steps."""
        response = self.sagemaker_session.sagemaker_client.list_pipeline_execution_steps(
            PipelineExecutionArn=self.arn
        )
        return response["PipelineExecutionSteps"]

    def wait(self, delay=30, max_attempts=60):
        """Waits for a pipeline execution.

        Args:
            delay (int): The polling interval. (Defaults to 30 seconds)
            max_attempts (int) The maximum number of polling attempts.
                (Defaults to 60 polling attempts)
        """
        waiter_id = "PipelineExecutionComplete"
        # TODO: this waiter should be included in the botocore
        model = botocore.waiter.WaiterModel(
            {
                "version": 2,
                "waiters": {
                    waiter_id: {
                        "delay": delay,
                        "maxAttempts": max_attempts,
                        "operation": "DescribePipelineExecution",
                        "acceptors": [
                            {
                                "expected": "Succeeded",
                                "matcher": "path",
                                "state": "success",
                                "argument": "PipelineExecutionStatus",
                            },
                            {
                                "expected": "Failed",
                                "matcher": "path",
                                "state": "failure",
                                "argument": "PipelineExecutionStatus",
                            },
                        ],
                    }
                },
            }
        )
        waiter = botocore.waiter.create_waiter_with_client(
            waiter_id, model, self.sagemaker_session.sagemaker_client
        )
        waiter.wait(PipelineExecutionArn=self.arn)
