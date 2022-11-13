#    Copyright 2022 Frank V. Castellucci
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#        http://www.apache.org/licenses/LICENSE-2.0
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

# -*- coding: utf-8 -*-


"""Sui RPC Clients."""

import json
import base64
from json import JSONDecodeError
from typing import Any, Union
import httpx
from pysui.abstracts import SyncHttpRPC, RpcResult
from pysui.sui.sui_types import ObjectID, SuiTxBytes, ObjectInfo, SuiAddress, from_object_descriptor, from_object_type
from pysui.sui.sui_config import SuiConfig
from pysui.sui.sui_builders import (
    DryRunTransaction,
    GetRpcAPI,
    SuiBaseBuilder,
    ExecuteTransaction,
    SuiRequestType,
    GetObjectsOwnedByAddress,
    GetObject,
    GetPackage,
)
from pysui.sui.sui_apidesc import build_api_descriptors, SuiApi
from pysui.sui.sui_txn_validator import validate_api
from pysui.sui.sui_excepts import SuiRpcApiNotAvailable


class SuiRpcResult(RpcResult):
    """Sui RpcResult."""

    def __init__(self, result_status: bool, result_string: str, result_data: Any = None) -> None:
        """Initialize a new RpcResult."""
        super().__init__()
        self._status: bool = result_status
        self._result_str: str = result_string
        self._data: Any = result_data

    def is_ok(self) -> bool:
        """Ease of use status."""
        return self._status is True

    def is_err(self) -> bool:
        """Ease of use status."""
        return self._status is True

    @property
    def result_data(self) -> Any:
        """Get result data."""
        return self._data

    @property
    def result_string(self) -> str:
        """Get result data."""
        return self._result_str


class SuiClient(SyncHttpRPC):
    """Sui Syncrhonous Client."""

    def __init__(self, config: SuiConfig) -> None:
        """Client initializer."""
        super().__init__(config)
        self._client = httpx.Client()
        self._rpc_api = {}
        self._build_api_descriptors()

    def _generate_data_block(self, data_block: dict, method: str, params: list) -> dict:
        """Build the json data block for Rpc."""
        data_block["method"] = method
        data_block["params"] = params
        return data_block

    def _build_api_descriptors(self):
        """Fetch RPC method descrptors."""
        builder = GetRpcAPI()
        try:
            result = self._client.post(
                self.config.rpc_url,
                headers=builder.header,
                json=self._generate_data_block(builder.data_dict, builder.method, builder.params),
            ).json()
            self._rpc_api, self._schema_dict = build_api_descriptors(result)
        except JSONDecodeError as jexc:
            raise jexc
        except httpx.ReadTimeout as hexc:
            raise hexc

    def api_exists(self, api_name: str) -> bool:
        """Check if API supported in RPC host."""
        return api_name in self._rpc_api

    @property
    def rpc_api(self) -> dict:
        """Return entire dictionary of RPC API methods."""
        return self._rpc_api

    def _api_method(self, method_name: str) -> SuiApi:
        """Get the method definition."""

    def _argument_check(self, _api_method: SuiApi, builder: SuiBaseBuilder) -> SuiBaseBuilder:
        """Perform argument validations."""
        return builder

    def _execute(self, builder: SuiBaseBuilder) -> Union[SuiRpcResult, Exception]:
        """Execute the builder construct."""
        parm_results = [y for x, y in validate_api(self._rpc_api[builder.method], builder)]
        jblock = self._generate_data_block(builder.data_dict, builder.method, parm_results)
        # import json
        # jout = json.dumps(jblock, indent=2)
        # print(f"{jout}")
        try:
            return SuiRpcResult(
                True,
                None,
                self._client.post(
                    self.config.rpc_url,
                    headers=builder.header,
                    json=jblock,
                ).json(),
            )
        except JSONDecodeError as jexc:
            return SuiRpcResult(False, f"JSON Decoder Error {jexc.msg}", vars(jexc))
        except httpx.ReadTimeout as hexc:
            return SuiRpcResult(False, "HTTP read timeout error", vars(hexc))

    def execute(self, builder: SuiBaseBuilder, dry_run: bool = False) -> Union[SuiRpcResult, Exception]:
        """Execute the builder construct."""
        if not builder.method in self._rpc_api:
            raise SuiRpcApiNotAvailable(builder.method)
        if not builder.txn_required:
            result = self._execute(builder)
            if result.is_ok():
                if "error" in result.result_data:
                    return result
                return SuiRpcResult(True, None, builder.handle_return(result.result_data["result"]))
            return result
        return self._signed_execution(builder, dry_run)

    def _signed_execution(self, builder: SuiBaseBuilder, dry_run: bool = False) -> Union[SuiRpcResult, Exception]:
        """Subit base transaction, sign valid result and execute."""
        result = self._execute(builder)
        if result.is_ok():
            result = result.result_data
            if "error" in result:
                return SuiRpcResult(False, result["error"]["message"], None)
            kpair = self.config.keypair_for_address(builder.authority)
            b64tx_bytes = result["result"]["txBytes"]
            # Dry run the transaction
            if dry_run:
                builder = DryRunTransaction()
                builder.set_pub_key(kpair.public_key).set_tx_bytes(SuiTxBytes(b64tx_bytes)).set_signature(
                    kpair.private_key.sign(base64.b64decode(b64tx_bytes))
                ).set_sig_scheme(kpair.scheme)
                raise NotImplementedError("Data handling for dry-run result not ready.")
            else:
                builder = ExecuteTransaction()
                builder.set_pub_key(kpair.public_key).set_tx_bytes(SuiTxBytes(b64tx_bytes)).set_signature(
                    kpair.private_key.sign(base64.b64decode(b64tx_bytes))
                ).set_sig_scheme(kpair.scheme).set_request_type(SuiRequestType.WAITFORLOCALEXECUTION)
            result = self._execute(builder)
            if result.is_ok():
                if "error" in result.result_data:
                    return SuiRpcResult(False, result.result_data["error"]["message"], None)
                # print(json.dumps(result.result_data["result"], indent=2))
                return SuiRpcResult(True, None, builder.handle_return(result.result_data["result"]))
        return result

    @property
    def rpc_api_names(self) -> list[str]:
        """Return names of RPC API methods."""
        return list(self._rpc_api.keys())

    # Build and execute convenience methods

    def get_address_object_descriptors(
        self, claz: ObjectInfo = None, address: SuiAddress = None
    ) -> Union[SuiRpcResult, Exception]:
        """Get object descriptors for address.

        :param claz: Class type to filter result on. If None then ObjectInfo types will be returned
        :type claz: ObjectInfo
        :param address: The address of which is being queried. If None then currrent `active_address` is used
        :type address: SuiAddress
        :raises: :class:`SuiException`: if returned from `self.execute`

        :returns: A list of ObjectInfo objects
        :rtype: SuiRpcResult
        """
        claz = claz if claz else ObjectInfo
        builder = GetObjectsOwnedByAddress(address if address else self.config.active_address)
        result = self.execute(builder)
        if result.is_ok():
            result = result.result_data
            type_descriptors = []
            for sui_objdesc in result:
                sui_type = from_object_descriptor(sui_objdesc)
                if isinstance(sui_type, claz):
                    type_descriptors.append(sui_type)
            return SuiRpcResult(True, None, type_descriptors)
        return result

    def get_object(self, identifier: ObjectID) -> Union[SuiRpcResult, Exception]:
        """Get specific object by it's identifier.

        :param identifier: The ObjectID of object being queried.
        :type identifier: ObjectID
        :raises: :class:`SuiException`: if returned from `self.execute`

        :returns: The objeect's data
        :rtype: SuiRpcResult
        """
        result = self.execute(GetObject(identifier))
        if result.is_ok():
            result = result.result_data
            if result["status"] != "Exists":
                return SuiRpcResult(False, f"Object {identifier} {result['status']}", None)
            return SuiRpcResult(True, None, from_object_type(result["details"]))
        return result

    def get_objects_for(self, identifiers: list[ObjectID]) -> Union[SuiRpcResult, Exception]:
        """Get objects for the list of identifiers.

        :param identifiers: The list of ObjectID's being queried.
        :type identifiers: list
        :raises: :class:`SuiException`: if returned from `self.execute`

        :returns: A list of object data
        :rtype: SuiRpcResult
        """
        obj_types = []
        for identity in identifiers:
            result = self.get_object(identity)
            if result.is_ok():
                obj_types.append(result.result_data)
            else:
                return result
        return SuiRpcResult(True, None, obj_types)

    def get_package(self, package_id: ObjectID) -> Union[SuiRpcResult, Exception]:
        """Get details of Sui package.

        :param package_id: The ObjectID of object being queried.
        :type package_id: ObjectID
        :raises: :class:`SuiException`: if returned from `self.execute`

        :returns: The package detail data
        :rtype: SuiRpcResult
        """
        result = self.execute(GetPackage(package_id))
        return result
