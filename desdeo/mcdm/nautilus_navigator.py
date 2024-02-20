"""Functions related to the NAUTILUS Navigator method are defined here.

Reference of the method:

Ruiz, Ana B., et al. "NAUTILUS Navigator: free search interactive multiobjective
optimization without trading-off." Journal of Global Optimization 74.2 (2019):
213-231.
"""

import numpy as np
from pydantic import BaseModel, Field

from desdeo.problem import (
    Problem,
    get_nadir_dict,
    numpy_array_to_objective_dict,
    objective_dict_to_numpy_array,
)
from desdeo.tools.generics import CreateSolverType, SolverResults
from desdeo.tools.scalarization import (
    add_lte_constraints,
    add_scalarization_function,
    create_asf,
    create_epsilon_constraints,
)
from desdeo.tools.utils import guess_best_solver


class NAUTILUS_Response(BaseModel):  # NOQA: N801
    """The response of the NAUTILUS Navigator method."""

    step_number: int = Field(description="The step number associted with this response.")
    distance_to_front: float = Field(description=(
        "The distance travelled to the Pareto front. "
        "The distance is a ratio of the distances between the nadir and navigation point, and "
        "the nadir and the reachable objective vector. The distance is given in percentage."
        ))
    reference_point: dict | None = Field(description="The reference point used in the step.")
    navigation_point: dict = Field(description="The navigation point used in the step.")
    reachable_solution: dict | None = Field(description="The reachable solution found in the step.")
    reachable_bounds: dict = Field(description="The reachable bounds found in the step.")


class NautilusNavigatorError(Exception):
    """Raised when an exception is encountered with procedures related to NAUTILUS Navigator."""


def calculate_navigation_point(
    problem: Problem,
    previous_navigation_point: dict[str, float],
    reachable_objective_vector: dict[str, float],
    number_of_steps_remaining: int,
) -> dict[str, float]:
    """Calculates the navigation point.

    The navigation point based on the previous navigation
    point, number of navigation steps remaining, and the reachable objective
    vector from the new navigation point.

    Args:
        problem (Problem): the problem being solved.
        previous_navigation_point (dict[str, float]): the previous navigation point.
        reachable_objective_vector (dict[str, float]): the current reachable objective vector from the navigation point.
        number_of_steps_remaining (int): the number of steps remaining in the navigation. Must be greater than 0.

    Raises:
        NautilusNavigatorError: when the given number of steps remaining is less than 0.

    Returns:
        list[float]: the navigation point.
    """
    if number_of_steps_remaining <= 0:
        msg = f"The given number of steps remaining ({number_of_steps_remaining=}) must be greater than 0."
        raise NautilusNavigatorError(msg)

    z_prev = objective_dict_to_numpy_array(problem, previous_navigation_point)
    f = objective_dict_to_numpy_array(problem, reachable_objective_vector).T  #
    rs = number_of_steps_remaining

    # return the new navigation point
    z = ((rs - 1) / (rs)) * z_prev + f / rs

    return numpy_array_to_objective_dict(problem, z)


def solve_reachable_bounds(
    problem: Problem, navigation_point: dict[str, float], create_solver: CreateSolverType | None = None
) -> tuple[dict[str, float], dict[str, float]]:
    """Computes the current reachable (upper and lower) bounds of the solutions in the objective space.

    The reachable bound are computed based on the current navigation point. The bounds are computed by
    solving an epsilon constraint problem.

    Args:
        problem (Problem): the problem being solved.
        navigation_point (dict[str, float]): the navigation point limiting the
            reachable area. The key is the objective function's symbol and the value
            the navigation point.
        create_solver (CreateSolverType | None, optional): a function of type CreateSolverType that returns a solver.
            If None, then a solver is utilized bases on the problem's properties. Defaults to None.

    Raises:
        NautilusNavigationError: when optimization of an epsilon constraint problem is not successful.

    Returns:
        tuple[dict[str, float], dict[str, float]]: a tuple of dicts, where the first dict are the lower bounds and the
            second element the upper bounds, the key is the symbol of each objective.
    """
    # If an objective is to be maximized, then the navigation point component of that objective should be
    # multiplied by -1.
    const_bounds = {
        objective.symbol: -1 * navigation_point[objective.symbol]
        if objective.maximize
        else navigation_point[objective.symbol]
        for objective in problem.objectives
    }

    # if a solver creator was provided, use that, else, guess the best one
    _create_solver = guess_best_solver(problem) if create_solver is None else create_solver

    lower_bounds = {}
    upper_bounds = {}
    for objective in problem.objectives:
        # symbols to identify the objectives to be constrained
        target_expr, const_exprs = create_epsilon_constraints(
            problem, objective_symbol=objective.symbol, epsilons=const_bounds
        )

        # solve lower bounds
        # add scalarization
        eps_problem, target = add_scalarization_function(problem, target_expr, "target")

        # add constraints
        eps_problem = add_lte_constraints(
            eps_problem, const_exprs, [f"eps_{i}" for i in range(1, len(const_exprs) + 1)]
        )

        # solve
        solver = _create_solver(eps_problem)
        res = solver(target)

        if not res.success:
            # could not optimize eps problem
            msg = (
                f"Optimizing the epsilon constrait problem for the objective "
                f"{objective.symbol} was not successful. Reason: {res.message}"
            )
            raise NautilusNavigatorError(msg)

        lower_bound = res.optimal_objectives[objective.symbol]

        if isinstance(lower_bound, list):
            lower_bound = lower_bound[0]

        # solver upper bounds
        # the lower bounds is set as in the NAUTILUS method, e.g., taken from
        # the current itration/navigation point
        if isinstance(navigation_point[objective.symbol], list):
            upper_bound = navigation_point[objective.symbol][0]
        else:
            upper_bound = navigation_point[objective.symbol]

        # add the lower and upper bounds logically depending whether an objective is to be maximized or minimized
        lower_bounds[objective.symbol] = lower_bound if not objective.maximize else upper_bound
        upper_bounds[objective.symbol] = upper_bound if not objective.maximize else lower_bound

    return lower_bounds, upper_bounds


def solve_reachable_solution(
    problem: Problem,
    reference_point: dict[str, float],
    previous_nav_point: dict[str, float],
    create_solver: CreateSolverType | None = None,
) -> SolverResults:
    """Calculates the reachable solution on the Pareto optimal front.

    For the calculation to make sense in the context of NAUTILUS Navigator, the reference point
    should be bounded by the reachable bounds present at the navigation step the
    reference point has been given.

    In practice, the reachable solution is calculated by solving an achievement
    scalarizing function.

    Args:
        problem (Problem): the problem being solved.
        reference_point (dict[str, float]): the reference point to project on the Pareto optimal front.
        previous_nav_point (dict[str, float]): the previous navigation point. The reachable solution found
            is always better than the previous navigation point.
        create_solver (CreateSolverType | None, optional): a function of type CreateSolverType that returns a solver.
            If None, then a solver is utilized bases on the problem's properties. Defaults to None.

    Returns:
        SolverResults: the results of the projection.
    """
    # check solver
    _create_solver = guess_best_solver(problem) if create_solver is None else create_solver

    # create and add scalarization function
    reference_point = objective_dict_to_numpy_array(problem, reference_point).tolist()
    sf = create_asf(problem, reference_point, reference_in_aug=True)
    problem_w_asf, target = add_scalarization_function(problem, sf, "asf")

    # Note: We do not solve the global problem. Instead, we solve this constrained problem:
    const_exprs = [
        f"{obj.symbol}_min - {previous_nav_point[obj.symbol] * (-1 if obj.maximize else 1)}"
        for obj in problem.objectives
    ]
    problem_w_asf = add_lte_constraints(
        problem_w_asf, const_exprs, [f"const_{i}" for i in range(1, len(const_exprs) + 1)]
    )

    # solve the problem
    solver = _create_solver(problem_w_asf)
    return solver(target)


def calculate_distance_to_front(
    problem: Problem, navigation_point: dict[str, float], reachable_objective_vector: dict[str, float]
) -> float:
    """Calculates the distance to the Pareto optimal front from a navigation point.

    It is assumed that a nadir point is defined for the problem.

    Args:
        problem (Problem): the problem being solved.
        navigation_point (dict[str, float]): the current navigation point.
        reachable_objective_vector (dict[str, float]): the current reachable objective vector from the navigation point.

    Raises:
        NautilusNavigatorError: all or some of the components of the problem's nadir point
            are not defined.

    Returns:
        float: the distance to the front.
    """
    nadir_point = objective_dict_to_numpy_array(problem, get_nadir_dict(problem))
    if None in nadir_point:
        msg = (
            f"Some or all the nadir values for the given problem are 'None': {nadir_point}. "
            "The nadir point must be fully defined."
        )
        raise NautilusNavigatorError(msg)

    z_nav = objective_dict_to_numpy_array(problem, navigation_point)
    f = objective_dict_to_numpy_array(problem, reachable_objective_vector)

    return (np.linalg.norm(z_nav - nadir_point) / np.linalg.norm(f - nadir_point)) * 100


# NAUTILUS Navigator initializer and steppers


def navigator_init(problem: Problem, create_solver: CreateSolverType | None = None) -> NAUTILUS_Response:
    """Initializes the NAUTILUS method.

    Creates the initial response of the method, which sets the navigation point to the nadir point
    and the reachable bounds to the ideal and nadir points.

    Args:
        problem (Problem): The problem to be solved.
        create_solver (CreateSolverType | None, optional): The solver to use. Defaults to ???.

    Returns:
        NAUTILUS_Response: The initial response of the method.
    """
    nav_point = get_nadir_dict(problem)
    lower_bounds, upper_bounds = solve_reachable_bounds(problem, nav_point, create_solver=create_solver)
    return NAUTILUS_Response(
        distance_to_front=0,
        navigation_point=nav_point,
        reachable_bounds={"lower_bounds": lower_bounds, "upper_bounds": upper_bounds},
        reachable_solution=None,
        reference_point=None,
        step_number=0,
    )


def navigator_step(  # NOQA: PLR0913
    problem: Problem,
    steps_remaining: int,
    step_number: int,
    nav_point: dict,
    create_solver: CreateSolverType | None = None,
    reference_point: dict | None = None,
    reachable_solution: dict | None = None,
) -> NAUTILUS_Response:
    """Performs a step of the NAUTILUS method.

    Args:
        problem (Problem): The problem to be solved.
        steps_remaining (int): The number of steps remaining.
        step_number (int): The current step number. Just used for the response.
        nav_point (dict): The current navigation point.
        create_solver (CreateSolverType | None, optional): The solver to use. Defaults to None.
        reference_point (dict | None, optional): The reference point provided by the DM. Defaults to None, in which
        case it is assumed that the DM has not changed their preference. The algorithm uses the last reachable solution,
        which must be provided in this case.
        reachable_solution (dict | None, optional): The previous reachable solution. Must only be provided if the DM
        has not changed their preference. Defaults to None.

    Raises:
        NautilusNavigatorError: If neither reference_point nor reachable_solution is provided.
        NautilusNavigatorError: If both reference_point and reachable_solution are provided.

    Returns:
        NAUTILUS_Response: The response of the method after the step.
    """
    if reference_point is None and reachable_solution is None:
        raise NautilusNavigatorError("Either reference_point or reachable_solution must be provided.")

    if reference_point is not None and reachable_solution is not None:
        raise NautilusNavigatorError("Only one of reference_point or reachable_solution should be provided.")

    if reference_point is not None:
        opt_result = solve_reachable_solution(problem, reference_point, nav_point, create_solver)
        reachable_point = opt_result.optimal_objectives
    else:
        reachable_point = reachable_solution

    # update nav point
    new_nav_point = calculate_navigation_point(problem, nav_point, reachable_point, steps_remaining)

    # update_bounds

    lower_bounds, upper_bounds = solve_reachable_bounds(problem, new_nav_point, create_solver=create_solver)

    distance = calculate_distance_to_front(problem, new_nav_point, reachable_point)

    return NAUTILUS_Response(
        step_number=step_number,
        distance_to_front=distance,
        navigation_point=new_nav_point,
        reachable_solution=reachable_point,
        reference_point=reference_point,
        reachable_bounds={"lower_bounds": lower_bounds, "upper_bounds": upper_bounds},
    )


def navigator_all_steps(
    problem: Problem,
    steps_remaining: int,
    reference_point: dict,
    previous_responses: list[NAUTILUS_Response],
    create_solver: CreateSolverType | None = None,
):
    """Performs all steps of the NAUTILUS method.

    NAUTILUS needs to be initialized before calling this function. Once initialized, this function performs all
    steps of the method. However, this method need not start from the beginning. The method conducts "steps_remaining"
    number of steps from the last navigation point. The last navigation point is taken from the last response in
    "previous_responses" list. The first step in this algorithm always involves recalculating the reachable solution.
    All subsequest steps are precalculated without recalculating the reachable solution, with the assumption that the
    reference point has not changed. It is up to the user to only show the steps that the DM thinks they have taken.

    Args:
        problem (Problem): The problem to be solved.
        steps_remaining (int): The number of steps remaining.
        reference_point (dict): The reference point provided by the DM.
        previous_responses (list[NAUTILUS_Response]): The previous responses of the method.
        create_solver (CreateSolverType | None, optional): The solver to use. Defaults to None, in which case the
            algorithm will guess the best solver for the problem.

    Returns:
        list[NAUTILUS_Response]: The new responses of the method after all steps. Note, as only new responses are
            returned, the length of the list is equal to "steps_remaining". The analyst should append these responses
            to the "previous_responses" list to keep track of the entire process.
    """
    responses: list[NAUTILUS_Response] = []
    nav_point = previous_responses[-1].navigation_point
    step_number = previous_responses[-1].step_number + 1
    first_iteration = True
    reachable_solution = dict
    while steps_remaining > 0:
        if first_iteration:
            response = navigator_step(
                problem,
                steps_remaining=steps_remaining,
                step_number=step_number,
                nav_point=nav_point,
                reference_point=reference_point,
                create_solver=create_solver,
            )
            first_iteration = False
        else:
            response = navigator_step(
                problem,
                steps_remaining=steps_remaining,
                step_number=step_number,
                nav_point=nav_point,
                reachable_solution=reachable_solution,
                create_solver=create_solver,
            )
        response.reference_point = reference_point
        responses.append(response)
        reachable_solution = response.reachable_solution
        nav_point = response.navigation_point
        steps_remaining -= 1
        step_number += 1
    return responses


def step_back_index(responses: list[NAUTILUS_Response], step_number: int) -> int:
    """Find the index of the response with the given step number.

    Note, multiple responses can have the same step
    number. This may happen if the DM takes a step back. In this case, the latest response with the given step number
    is returned. Note, as we precalculate all the responses, it is up to the analyst to show the steps that the DM
    thinks they have taken. Without this, the DM may be confused. In the worst case, the DM may take a step "back to
    the future".

    Args:
        responses (list[NAUTILUS_Response]): Responses returned by the NAUTILUS method.
        step_number (int): The step number to go back to.

    Returns:
        int : The index of the response with the given step number.
    """
    relevant_indices = [i for i, response in enumerate(responses) if response.step_number == step_number]
    # Choose latest index
    return relevant_indices[-1]


def get_current_path(all_responses: list[NAUTILUS_Response]) -> list[int]:
    """Get the path of the current responses.

    All responses may contain steps that the DM has gone back on. This function returns the path of the current active
    path being followed by the DM. The path is a list of indices of the responses in the "all_responses" list. Note that
    the path includes all steps until reaching the Pareto front (or whatever the last response is). It is up to the
    analyst/GUI to only show the steps that the DM has taken.

    Args:
        all_responses (list[NAUTILUS_Response]): All responses returned by the NAUTILUS method.

    Returns:
        list[int]: The path of the current active responses.
    """
    total_steps = all_responses[-1].step_number
    current_index = len(all_responses) - 1
    path: list[int] = [current_index]
    total_steps -= 1

    while total_steps >= 0:
        found_step = False
        while not found_step:
            current_index -= 1
            if all_responses[current_index].step_number == total_steps:
                path.append(current_index)
                found_step = True
        total_steps -= 1
    return list(reversed(path))


if __name__ == "__main__":
    from desdeo.problem import binh_and_korn, get_ideal_dict

    problem = binh_and_korn()

    # initialization
    nav_point = get_nadir_dict(problem)
    lower_bounds = get_ideal_dict(problem)
    upper_bounds = get_nadir_dict(problem)

    step = 1
    steps_remaining = 100

    # get reference point
    reference_point = {"f_1": 100.0, "f_2": 8.0}

    # calculate reachable solution (direction)
    opt_result = solve_reachable_solution(problem, reference_point)

    assert opt_result.success

    reachable_point = opt_result.optimal_objectives

    # update nav point
    nav_point = calculate_navigation_point(problem, nav_point, reachable_point, steps_remaining)
    print(f"{nav_point=}")

    # update_bounds
    lower_bounds, upper_bounds = solve_reachable_bounds(problem, nav_point)

    distance = calculate_distance_to_front(problem, nav_point, reachable_point)

    step += 1
    steps_remaining -= 1

    # no new reference point, reachable point (direction) stays the same
    # update nav point
    nav_point = calculate_navigation_point(problem, nav_point, reachable_point, steps_remaining)
    print(f"{nav_point=}")

    # update bounds
    lower_bounds, upper_bounds = solve_reachable_bounds(problem, nav_point)

    distance = calculate_distance_to_front(problem, nav_point, reachable_point)

    step += 1
    steps_remaining -= 1

    # new reference point
    reference_point = {"f_1": 80.0, "f_2": 9.0}

    # calculate reachable solution (direction)
    opt_result = solve_reachable_solution(problem, reference_point)

    assert opt_result.success

    reachable_point = opt_result.optimal_objectives

    # update nav point
    nav_point = calculate_navigation_point(problem, nav_point, reachable_point, steps_remaining)
    print(f"{nav_point=}")

    # update_bounds
    lower_bounds, upper_bounds = solve_reachable_bounds(problem, nav_point)

    distance = calculate_distance_to_front(problem, nav_point, reachable_point)

    step += 1
    steps_remaining -= 1

    # etc...
