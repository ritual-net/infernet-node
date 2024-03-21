from typing import Any, Type, Union, get_args

import dacite


def from_union(type_or_union: Union[Type[Any], Any], data: dict[Any, Any]) -> Any:
    """Parse a data dict into a dataclass, trying with all types in a Union.

    Recursive function to parse a dict into a dataclass, trying with all types
    in a Union until one works.

    NOTE: All subtypes of Union must also be dataclasses. Otherwise, dacite
    will throw an error.

    Args:
        type_or_union (Union[Type[Any], Any]): Type or Union to parse
        data (dict[Any, Any]): Data to parse

    Returns:
        Any: Parsed dataclass

    Raises:
        dacite.exceptions.WrongTypeError: If the data cannot be recursively parsed into
            type_or_union or any of its subtypes
    """
    if hasattr(type_or_union, "__origin__") and type_or_union.__origin__ is Union:
        # Union, recurse on each type
        for union_type in get_args(type_or_union):
            output = from_union(union_type, data)
            if output:
                return output

    else:
        # Base case: not a Union, just try with the provided type
        return dacite.from_dict(data_class=type_or_union, data=data)
