from __future__ import annotations
import copy
from typing import Optional, Tuple

from codemanip import code_utils

from srcmlcpp.cpp_types import CppParameter

from litgen.internal.adapt_function_params._lambda_adapter import LambdaAdapter
from litgen.internal.adapted_types import AdaptedFunction, AdaptedParameter
from litgen.options import LitgenOptions


def adapt_encapsulate_incomplete_types(
    adapted_func: AdaptedFunction,
) -> Optional[LambdaAdapter]:
    """
    We want to adapt function return value that use incomplete types (through opaque pointers) to use a capsule.

    For example, for the following code

    ````
    typedef struct Foo Foo;
    Foo *foo_new()
    ```

    generate an adapter lambda that looks like

    ```
    m.def("foo_new", []()
    {
        Foo *ptr = foo_new();

        return nb::capsule(ptr);
    }
    ```
    """
    options: LitgenOptions = adapted_func.options

    if not options.fn_encapsulate_incomplete_types__regex:
        return None

    needs_encapsulation: bool = False

    # Return value
    encapsulate_return_value: bool = True
    if (
        not adapted_func.cpp_adapted_function.has_return_type()
        or not code_utils.does_match_regex_or_matcher(
            options.fn_encapsulate_incomplete_types__regex,
            adapted_func.cpp_adapted_function.str_full_return_type(),
        )
    ):
        encapsulate_return_value = False
    else:
        needs_encapsulation = True

    param_list: list[Tuple[bool, AdaptedParameter]] = []
    for param in adapted_func.adapted_parameters():
        encapsulate_param: bool = code_utils.does_match_regex_or_matcher(
            options.fn_encapsulate_incomplete_types__regex,
            param.cpp_element().full_type(),
        )

        if encapsulate_param:
            needs_encapsulation = True

        param_list.append((encapsulate_param, param))

    if not needs_encapsulation:
        return None

    lambda_adapter: LambdaAdapter = LambdaAdapter()
    lambda_adapter.lambda_name = f"{adapted_func.cpp_adapted_function.function_name}_adapt_encapsulate_incomplete_types"
    lambda_adapter.new_function_infos = copy.deepcopy(adapted_func.cpp_adapted_function)

    # Parameters
    new_func_params: list[CppParameter] = []
    for encapsulate, param in param_list:
        param_name: str = param.cpp_element().decl.decl_name

        if not encapsulate:
            new_func_params.append(param.cpp_element())
            lambda_adapter.adapted_cpp_parameter_list.append(param_name)
            continue

        param_type: str = param.cpp_element().full_type()
        new_param_name: str = f"{param_name}_encapsulated"

        new_param: CppParameter = copy.deepcopy(param.cpp_element())
        new_param.decl.cpp_type.typenames = ["nb::capsule"]
        new_param.decl.decl_name = new_param_name
        new_param.decl.cpp_type.modifiers = []
        new_param.decl.cpp_type.specifiers = []
        new_param.decl.initial_value_code = ""

        new_func_params.append(new_param)
        lambda_adapter.lambda_input_code += (
            f"{param_type} {param_name} = static_cast<{param_type}>({new_param_name}.data());"
        )
        lambda_adapter.adapted_cpp_parameter_list.append(param_name)

    lambda_adapter.new_function_infos.parameter_list.parameters = new_func_params

    # Return value
    if encapsulate_return_value:
        lambda_adapter.new_function_infos.return_type.typenames = ["nb::object"]
        lambda_adapter.new_function_infos.return_type.modifiers = []

        # Taken mostly from apply_all_adapters.py
        def get_function_or_lambda_to_call(adapted_func: AdaptedFunction) -> str:
            if adapted_func.lambda_to_call is not None:
                return adapted_func.lambda_to_call
            if adapted_func.is_method():
                return f"self.{adapted_func.cpp_adapted_function.function_name_with_specialization()}"
            return adapted_func.cpp_adapted_function.qualified_function_name_with_specialization()

        def get_auto_r_equal_or_void(adapted_func: AdaptedFunction) -> str:
            if adapted_func.cpp_adapted_function.str_full_return_type() != "void":
                _auto = (
                    "auto&"
                    if adapted_func.cpp_adapted_function.returns_reference()
                    else "auto"
                )
                return f"{_auto} lambda_result ="
            return ""

        lambda_template_end: str = f"""
        {get_auto_r_equal_or_void(adapted_func)} {get_function_or_lambda_to_call(adapted_func)}({", ".join(lambda_adapter.adapted_cpp_parameter_list)});
        return nb::capsule(lambda_result);
        """

        lambda_adapter.lambda_template_end = code_utils.unindent_code(
            lambda_template_end, flag_strip_empty_lines=True
        )

    return lambda_adapter
