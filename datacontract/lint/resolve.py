import logging
import os

import fastjsonschema
import yaml
from fastjsonschema import JsonSchemaValueException

from datacontract.lint.files import read_file
from datacontract.lint.schema import fetch_schema
from datacontract.lint.urls import fetch_resource
from datacontract.model.data_contract_specification import \
    DataContractSpecification, Definition, Quality
from datacontract.model.exceptions import DataContractException


def resolve_data_contract(
    data_contract_location: str = None,
    data_contract_str: str = None,
    data_contract: DataContractSpecification = None,
    schema_location: str = None,
    inline_definitions: bool = False,
) -> DataContractSpecification:
    if data_contract_location is not None:
        return resolve_data_contract_from_location(data_contract_location, schema_location, inline_definitions)
    elif data_contract_str is not None:
        return resolve_data_contract_from_str(data_contract_str, schema_location, inline_definitions)
    elif data_contract is not None:
        return data_contract
    else:
        raise DataContractException(
            type="lint",
            result="failed",
            name="Check that data contract YAML is valid",
            reason="Data contract needs to be provided",
            engine="datacontract",
        )


def resolve_data_contract_from_location(
    location, schema_location: str = None, inline_definitions: bool = False, include_quality: bool = True
) -> DataContractSpecification:
    if location.startswith("http://") or location.startswith("https://"):
        data_contract_str = fetch_resource(location)
    else:
        data_contract_str = read_file(location)
    return resolve_data_contract_from_str(data_contract_str, schema_location, inline_definitions, include_quality)


def inline_definitions_into_data_contract(spec: DataContractSpecification):
    for model in spec.models.values():
        for field in model.fields.values():
            # If ref_obj is not empty, we've already inlined definitions.
            if not field.ref and not field.ref_obj:
                continue

            definition = resolve_definition_ref(field.ref, spec.definitions)
            field.ref_obj = definition

            for field_name in field.model_fields.keys():
                if field_name in definition.model_fields_set and field_name not in field.model_fields_set:
                    setattr(field, field_name, getattr(definition, field_name))


def resolve_definition_ref(ref, definitions) -> Definition:
    if ref.startswith("http://") or ref.startswith("https://"):
        definition_str = fetch_resource(ref)
        definition_dict = to_yaml(definition_str)
        return Definition(**definition_dict)

    elif ref.startswith("#/definitions/"):
        definition_name = ref.split("#/definitions/")[1]
        return definitions[definition_name]
    else:
        raise DataContractException(
            type="lint",
            result="failed",
            name="Check that data contract YAML is valid",
            reason=f"Cannot resolve reference {ref}",
            engine="datacontract",
        )


def resolve_quality_ref(quality: Quality):
    """
    Return the content of a ref file path
    @param quality data contract quality specification
    """
    if isinstance(quality.specification, dict):
        specification = quality.specification
        if quality.type == "great-expectations":
            for model, model_quality in specification.items():
                specification[model] = get_quality_ref_file(model_quality)
        else:
            if "$ref" in specification:
                quality.specification = get_quality_ref_file(specification)


def get_quality_ref_file(quality_spec: str | object) -> str | object:
    """
    Get the file associated with a quality reference
    @param quality_spec quality specification
    @returns: the content of the quality file
    """
    if isinstance(quality_spec, dict) and "$ref" in quality_spec:
        ref = quality_spec["$ref"]
        if not os.path.exists(ref):
            raise DataContractException(
                type="export",
                result="failed",
                name="Check that data contract quality is valid",
                reason=f"Cannot resolve reference {ref}",
                engine="datacontract",
            )
        with open(ref, "r") as file:
            quality_spec = file.read()
    return quality_spec


def resolve_data_contract_from_str(
    data_contract_str, schema_location: str = None, inline_definitions: bool = False, include_quality: bool = False
) -> DataContractSpecification:
    data_contract_yaml_dict = to_yaml(data_contract_str)
    validate(data_contract_yaml_dict, schema_location)

    spec = DataContractSpecification(**data_contract_yaml_dict)

    if inline_definitions:
        inline_definitions_into_data_contract(spec)
    if spec.quality and include_quality:
        resolve_quality_ref(spec.quality)

    return spec


def to_yaml(data_contract_str):
    try:
        yaml_dict = yaml.safe_load(data_contract_str)
        return yaml_dict
    except Exception as e:
        logging.warning(f"Cannot parse YAML. Error: {str(e)}")
        raise DataContractException(
            type="lint",
            result="failed",
            name="Check that data contract YAML is valid",
            reason=f"Cannot parse YAML. Error: {str(e)}",
            engine="datacontract",
        )


def validate(data_contract_yaml, schema_location: str = None):
    schema = fetch_schema(schema_location)
    try:
        fastjsonschema.validate(schema, data_contract_yaml)
        logging.debug("YAML data is valid.")
    except JsonSchemaValueException as e:
        logging.warning(f"Data Contract YAML is invalid. Validation error: {e.message}")
        raise DataContractException(
            type="lint",
            result="failed",
            name="Check that data contract YAML is valid",
            reason=e.message,
            engine="datacontract",
        )
    except Exception as e:
        logging.warning(f"Data Contract YAML is invalid. Validation error: {str(e)}")
        raise DataContractException(
            type="lint",
            result="failed",
            name="Check that data contract YAML is valid",
            reason=str(e),
            engine="datacontract",
        )
