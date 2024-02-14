"""Different evaluators are defined for evaluating multiobjective optimization problems."""

import polars as pl
from pydantic import BaseModel, Field

from desdeo.problem.json_parser import MathParser, replace_str
from desdeo.problem.schema import Problem, ObjectiveTypeEnum

SUPPORTED_EVALUATOR_TYPES = ["polars"]


class EvaluatorResult(BaseModel):
    """A model to store the results computed by Evaluator."""

    variable_values: dict[str, list[float]] = Field(
        description=(
            "The decision variable values utilized in the evaluation. The keys of the dict are the decision variable"
            " symbols followed by a list of values corresponding to the variable."
        )
    )
    objective_values: dict[str, list[float]] = Field(
        description=(
            "The evaluated objective function values. The keys of the dict are objective function symbols followed"
            " by a list of values corresponding to the objective function."
        )
    )
    extra_values: dict[str, list[float]] | None = Field(
        description=(
            "The evaluated extra function values. The keys of the dict are the extra function symbols followed"
            " by a list of values corresponding to the extra function. Optional."
        ),
        default=None,
    )
    constraint_values: dict[str, list[float]] | None = Field(
        description=(
            "The evaluated constraint values. The keys of the dict"
            "are the constraint symbols followed by a list of values corresponding to the constraint. Optional."
        ),
        default=None,
    )
    scalarization_values: dict[str, list[float]] | None = Field(
        description=(
            "The evaluated scalarization function values. The"
            " keys of the dict are the names of the scalarization functions followed by a list corresponding to the"
            " functions. Optional."
        ),
        default=None,
    )


class EvaluatorError(Exception):
    """Error raised when exceptions are encountered in an Evaluator class."""


class GenericEvaluator:
    """A class for creating evaluators for multiobjective optimization problems.

    The evaluator is to be used with different optimizers. GenericEvaluator is specifically
    for solvers that do not require an exact formulation of the problem, but rather work
    solely on the input and output values of the problem being solved. This evaluator might not
    be suitable for computationally expensive problems, or mixed-integer problems. This
    evaluator is suitable for many Python-based solvers, such as `scipy.optimize.minimize`.

    See the evaluators TO BE DONE for ruther details for approaching other kinds of problems.
    """

    ### Initialization (no need for decision variables yet)
    # 1. Create a math parser with parser type 'evaluator_type'. Defaults to 'polars'.
    # 2. Check for any constants in the definition of the problem. Replace the constants, if they exist,
    #    with their numerical values in all the function expressions found in problem.
    # 3. Parse the function expressions into a dataframe.

    ### Evaluating (we have decision variables to evaluate problem)
    # 1. Evaluate the extra functions (if any) in the dataframe with the decision variables. Store the results
    #    in new columns of the dataframe.
    # 2. Evaluate the objectie functions based on the decision variables and the extra function values (if any).
    #    Store the results in the dataframe in their own columns.
    # 3. Evaluate the constraints (if any) based on the decision variables and extra function values (if any).
    #    Store the results in the dataframe in their own columns.
    # 4. Evalute the scalarization functions (if any) based on the objective function values and extra function values
    #    (if any). Store the results in the dataframe in their own columns.
    # 5. Return a pydantic dataclass with the results (decision variables, objective function values, constraint values,
    #    and scalarization function valeus).
    # 6. End.

    def __init__(self, problem: Problem, parser_type: str = "polars"):
        """Create an evaluator for a multiobjective optimization problem.

        Args:
            problem (Problem): The problem as a pydantic 'Problem' data class.
            parser_type (str): The type of parser used to parse the problem into a format
                that can be evaluated. Default 'polars'.
        """
        # Create a MathParser of type 'evaluator_type'.
        if parser_type not in SUPPORTED_EVALUATOR_TYPES:
            msg = (
                f"The provided 'parser_type' '{parser_type}' is not supported."
                " Must be one of {SUPPORTED_EVALUATOR_TYPES}."
            )
            raise EvaluatorError(msg)

        self.parser_type = parser_type

        # Gather any constants of the problem definition.
        self.problem_constants = problem.constants
        # Gather the objective functions
        self.problem_objectives = problem.objectives
        # Gather any constraints
        self.problem_constraints = problem.constraints
        # Gather any extra functions
        self.problem_extra = problem.extra_funcs
        # Gather any scalarization functions
        self.problem_scalarization = problem.scalarizations_funcs
        # Gather the decision variable symbols defined in the problem
        self.problem_variable_symbols = [var.symbol for var in problem.variables]
        # The discrete definition of (some) objectives
        self.discrete_definition = problem.discrete_definition

        # The below 'expressions' are list of tuples with symbol and expressions pairs, as (symbol, expression)
        # These must be defined in a specialized initialization step, see further below for an example.
        # Symbol and expressions pairs of the objective functions
        self.objective_expressions = None
        # Symbol and expressions pairs of any constraints
        self.constraint_expressions = None
        # Symbol and expressions pairs of any extra functions
        self.extra_expressions = None
        # Symbol and expression pairs of any scalarization functions
        self.scalarization_expressions = None

        # When parsing the expressions, branch into different initializations based on `parser_type`.
        # Setup the correct function to be called when the `evaluate` method is called based on the selected
        # `parser_type`
        # When defining support for different parsers in the evaluator, the support should be added below
        # as additional if-branches.
        if parser_type == "polars":
            # Note: `self.parser` is assumed to be set before continuing the initialization.
            self.parser = MathParser()
            self._polars_init()
            # Note, when calling an evaluate method, it is assumed the problem has been fully parsed.
            self.evaluate = self._polars_evaluate

        else:
            msg = f"Parser type of {parser_type} not yet supported."
            raise EvaluatorError(msg)

    def _polars_init(self):
        """Initialization of the evaluator for parser type 'polars'."""
        # If any constants are defined in problem, replace their symbol with the defined numerical
        # value in all the function expressions found in the Problem.
        if self.problem_constants is not None:
            # Objectives are always defined, cannot be None
            parsed_obj_funcs = {}
            for obj in self.problem_objectives:
                if obj.objective_type == ObjectiveTypeEnum.analytical:
                    # if analytical proceed with replacing the symbols.
                    tmp = obj.func
                    for c in self.problem_constants:
                        tmp = replace_str(tmp, c.symbol, c.value)
                    parsed_obj_funcs[f"{obj.symbol}"] = tmp
                elif obj.objective_type == ObjectiveTypeEnum.data_based:
                    # data-based objective
                    parsed_obj_funcs[f"{obj.symbol}"] = None
                else:
                    msg = (
                        f"Incorrect objective-type {obj.objective_type} encountered. "
                        f"Must be one of {ObjectiveTypeEnum}"
                    )
                    raise EvaluatorError(msg)

            # Do the same for any constraint expressions as well.
            if self.problem_constraints is not None:
                parsed_cons_funcs: dict | None = {}
                for con in self.problem_constraints:
                    tmp = con.func
                    for c in self.problem_constants:
                        tmp = replace_str(tmp, c.symbol, c.value)
                    parsed_cons_funcs[f"{con.symbol}"] = tmp
            else:
                parsed_cons_funcs = None

            # Do the same for any extra functions
            parsed_extra_funcs: dict | None = {}
            if self.problem_extra is not None:
                for extra in self.problem_extra:
                    tmp = extra.func
                    for c in self.problem_constants:
                        tmp = replace_str(tmp, c.symbol, c.value)
                    parsed_extra_funcs[f"{extra.symbol}"] = tmp
            else:
                parsed_extra_funcs = None

            # Do the same for any scalarization functions
            parsed_scal_funcs: dict | None = {}
            if self.problem_scalarization is not None:
                for scal in self.problem_scalarization:
                    tmp = scal.func
                    for c in self.problem_constants:
                        tmp = replace_str(tmp, c.symbol, c.value)
                    parsed_scal_funcs[f"{scal.symbol}"] = tmp
            else:
                parsed_scal_funcs = None
        else:
            # no constants defined, just collect all expressions as they are
            parsed_obj_funcs = {f"{objective.symbol}": objective.func for objective in self.problem_objectives}

            if self.problem_constraints is not None:
                parsed_cons_funcs = {f"{constraint.symbol}": constraint.func for constraint in self.problem_constraints}
            else:
                parsed_cons_funcs = None

            if self.problem_extra is not None:
                parsed_extra_funcs = {f"{extra.symbol}": extra.func for extra in self.problem_extra}
            else:
                parsed_extra_funcs = None

            if self.problem_scalarization is not None:
                parsed_scal_funcs = {f"{scal.symbol}": scal.func for scal in self.problem_scalarization}
            else:
                parsed_scal_funcs = None

        # Parse all functions into expressions. These are stored as tuples, as (symbol, parsed expression)
        # parse objectives
        # If no expression is given (data-based objective, then the expression is set to be 'None')
        self.objective_expressions = [
            (symbol, self.parser.parse(expression)) if expression is not None else None
            for symbol, expression in parsed_obj_funcs.items()
        ]

        # parse constraints, if any
        if parsed_cons_funcs is not None:
            self.constraint_expressions = [
                (symbol, self.parser.parse(expression)) for symbol, expression in parsed_cons_funcs.items()
            ]
        else:
            self.constraint_expressions = None

        # parse extra functions, if any
        if parsed_extra_funcs is not None:
            self.extra_expressions = [
                (symbol, self.parser.parse(expression)) for symbol, expression in parsed_extra_funcs.items()
            ]
        else:
            self.extra_expressions = None

        # parse scalarization functions, if any
        if parsed_scal_funcs is not None:
            self.scalarization_expressions = [
                (symbol, self.parser.parse(expression)) for symbol, expression in parsed_scal_funcs.items()
            ]
        else:
            self.scalarization_expressions = None

        # store the symbol and min or max multiplier as well (symbol, min/max multiplier [1 | -1])
        self.objective_mix_max_mult = [
            (objective.symbol, -1 if objective.maximize else 1) for objective in self.problem_objectives
        ]

        # create dataframe with the discrete representation, if any exists
        if self.discrete_definition is not None:
            self.discrete_df = pl.DataFrame(
                [self.discrete_definition.variable_values, self.discrete_definition.objective_values]
            )
        else:
            self.discrete_df = None

    def _polars_evaluate(self, xs: dict[str, list[float | int | bool]]) -> EvaluatorResult:
        """Evaluate the problem with the given decision variable values utilizing a polars dataframe.

        Args:
            xs (dict[str, list[float | int | bool]]): a dict with the decision variable symbols
            as the keys followed by the corresponding decision variable values stored in a list. The symbols
            must match the symbols defined for the decision variables defined in the `Problem` being solved.
            Each list in the dict should contain the same number of values.

        Returns:
            EvaluatorResult: the results of the evaluation. See `EvaluatorResult` for details.

        Note:
            At least `self.objective_expressions` must be defined before calling this method.
        """
        # An aggregate dataframe to store intermediate evaluation results.
        agg_df = pl.DataFrame(xs)

        # Evaluate any extra functions and put the results in the aggregate dataframe.
        if self.extra_expressions is not None:
            extra_columns = agg_df.select(*[expr.alias(symbol) for symbol, expr in self.extra_expressions])
            agg_df = agg_df.hstack(extra_columns)

        # Evaluate the objective functions and put the results in the aggregate dataframe.
        # obj_columns = agg_df.select(*[expr.alias(symbol) for symbol, expr in self.objective_expressions])
        # agg_df = agg_df.hstack(obj_columns)

        for symbol, expr in self.objective_expressions:
            if expr is not None:
                # expression given
                obj_col = agg_df.select(expr.alias(symbol))
                agg_df = agg_df.hstack(obj_col)
            else:
                # expr is note, therefore we must get the objective function's value somehow else, usually from data
                pass

        # Evaluate the minimization form of the objective functions
        # Note that the column name of these should be 'the objective function's symbol'_min
        # e.g., 'f_1' -> 'f_1_min'
        min_obj_columns = agg_df.select(
            *[
                (min_max_mult * pl.col(f"{symbol}")).alias(f"{symbol}_min")
                for symbol, min_max_mult in self.objective_mix_max_mult
            ]
        )
        agg_df = agg_df.hstack(min_obj_columns)

        # Evaluate any constraints and put the results in the aggregate dataframe
        if self.constraint_expressions is not None:
            cons_columns = agg_df.select(*[expr.alias(symbol) for symbol, expr in self.constraint_expressions])
            agg_df = agg_df.hstack(cons_columns)

        # Evaluate any scalarization functions and put the result in the aggregate dataframe
        if self.scalarization_expressions is not None:
            scal_columns = agg_df.select(*[expr.alias(symbol) for symbol, expr in self.scalarization_expressions])
            agg_df = agg_df.hstack(scal_columns)

        # Collect the results
        variable_values = {symbol: agg_df[symbol].to_list() for symbol in self.problem_variable_symbols}
        objective_values = {symbol: agg_df[symbol].to_list() for symbol, _ in self.objective_expressions}

        if self.constraint_expressions is not None:
            constraint_values = {symbol: agg_df[symbol].to_list() for symbol, _ in self.constraint_expressions}
        else:
            constraint_values = None

        if self.extra_expressions is not None:
            extra_values = {symbol: agg_df[symbol].to_list() for symbol, _ in self.extra_expressions}
        else:
            extra_values = None

        if self.scalarization_expressions is not None:
            scalarization_values = {symbol: agg_df[symbol].to_list() for symbol, _ in self.scalarization_expressions}
        else:
            scalarization_values = None

        return EvaluatorResult(
            variable_values=variable_values,
            objective_values=objective_values,
            extra_values=extra_values,
            constraint_values=constraint_values,
            scalarization_values=scalarization_values,
        )


def find_closest_points(xs, discrete_df, variable_symbols, objective_symbol):
    """
    # Prepare column names for the right side of the join
    right_cols = [f"{col}_right" for col in variable_symbols]

    # Rename columns in discrete_df for clarity in the cross join
    discrete_df_renamed = discrete_df.rename({col: f"{col}_right" for col in variable_symbols})

    # Cross join to compare every combination of points between xs and discrete_df
    combined_df = xs.join(discrete_df_renamed, how="cross")

    # Calculate Euclidean distances using dynamic column names
    distance_expr = sum(
        (pl.col(col) - pl.col(f"{col}_right"))**2 for col in variable_symbols
    ).sqrt().alias("distance")

    combined_df = combined_df.with_columns(distance_expr)

    # Group by the original xs columns and select the closest objective function value
    closest_points = combined_df.sort("distance").groupby(variable_symbols).agg(
        pl.first(objective_symbol).alias(f"{objective_symbol}")
    )
    return closest_points
    """

    xs_vars_only = xs[variable_symbols]

    results = []

    for row in xs_vars_only.rows(named=True):
        print(row)
        distance_expr = (
            sum((pl.col(var_symbol) - row[var_symbol]) ** 2 for var_symbol in variable_symbols).sqrt().alias("distance")
        )

        combined_df = discrete_df.with_columns(distance_expr)

        closest = combined_df.sort("distance").head(1)

        results.append(closest[f"{objective_symbol}"][0])

    return pl.DataFrame({f"{objective_symbol}": results})
