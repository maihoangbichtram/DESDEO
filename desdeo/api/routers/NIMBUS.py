"""Router for NIMBUS."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from numpy import allclose
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from desdeo.api.db import get_db
from desdeo.api.db_models import Problem as ProblemInDB
from desdeo.api.db_models import SolutionArchive, Preference
from desdeo.api.routers.UserAuth import get_current_user
from desdeo.api.schema import User
from desdeo.mcdm.nimbus import generate_starting_point, solve_intermediate_solutions, solve_sub_problems
from desdeo.problem.schema import Problem
from desdeo.tools import SolverResults

router = APIRouter(prefix="/nimbus")


class InitRequest(BaseModel):
    """The request to initialize the NIMBUS."""

    problem_id: int = Field(description="The ID of the problem to navigate.")
    method_id: int = Field(description="The ID of the method being used.")


class NIMBUSResponse(BaseModel):
    """The response from most NIMBUS endpoints."""

    objective_symbols: list[str] = Field(description="The symbols of the objectives.")
    objective_long_names: list[str] = Field(description="The names of the objectives.")
    units: list[str] | None = Field(description="The units of the objectives.")
    is_maximized: list[bool] = Field(description="Whether the objectives are to be maximized or minimized.")
    lower_bounds: list[float] = Field(description="The lower bounds of the objectives.")
    upper_bounds: list[float] = Field(description="The upper bounds of the objectives.")
    previous_preference: list[float] = Field(description="The previous preference used.")
    current_solutions: list[list[float]] = Field(description="The solutions from the current interation of nimbus.")
    saved_solutions: list[list[float]] = Field(description="The best candidate solutions saved by the decision maker.")
    all_solutions: list[list[float]] = Field(description="All solutions generated by NIMBUS in all iterations.")


class FakeNIMBUSResponse(BaseModel):
    """fake response for testing purposes."""

    message: str = Field(description="A simple message.")


class NIMBUSIterateRequest(BaseModel):
    """The request to iterate the NIMBUS algorithm."""

    problem_id: int = Field(description="The ID of the problem to be solved.")
    method_id: int = Field(description="The ID of the method being used.")
    preference: list[float] = Field(
        description=(
            "The preference as a reference point. Note, NIMBUS uses classification preference,"
            " we can construct it using this reference point and the reference solution."
        )
    )
    reference_solution: list[float] = Field(
        description="The reference solution to be used in the classification preference."
    )
    num_solutions: int | None = Field(
        description="The number of solutions to be generated in the iteration.", default=1
    )


class NIMBUSIntermediateSolutionRequest(BaseModel):
    """The request to generate an intermediate solution in NIMBUS."""

    problem_id: int = Field(description="The ID of the problem to be solved.")
    method_id: int = Field(description="The ID of the method being used.")

    reference_solution_1: list[float] = Field(
        description="The first reference solution to be used in the classification preference."
    )
    reference_solution_2: list[float] = Field(
        description="The reference solution to be used in the classification preference."
    )
    num_solutions: int | None = Field(
        description="The number of solutions to be generated in the iteration.", default=1
    )


class SaveRequest(BaseModel):
    """The request to save the solutions."""

    problem_id: int = Field(description="The ID of the problem to be solved.")
    solutions: list[list[float]] = Field(description="The solutions to be saved.")


@router.post("/initialize")
def init_nimbus(
    init_request: InitRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NIMBUSResponse | FakeNIMBUSResponse:
    """Initialize the NIMBUS algorithm.

    Args:
        init_request (InitRequest): The request to initialize the NIMBUS.
        user (Annotated[User, Depends(get_current_user)]): The current user.
        db (Annotated[Session, Depends(get_db)]): The database session.

    Returns:
        The response from the NIMBUS algorithm.
    """
    # Do database stuff here.
    problem_id = init_request.problem_id
    # Maybe it's fine if method ID comes from the request.
    # I guess this code does not need to know what the ID of Nimbus is.
    method_id = init_request.method_id
    problem = db.query(ProblemInDB).filter(ProblemInDB.id == problem_id).first()

    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found.")
    if problem.owner != user.index and problem.owner is not None:
        raise HTTPException(status_code=403, detail="Unauthorized to access chosen problem.")
    try:
        problem = Problem.model_validate(problem.value)
    except ValidationError:
        raise HTTPException(status_code=500, detail="Error in parsing the problem.") from ValidationError

    # See if there are previous solutions in the database for this problem
    solutions = (
        db.query(SolutionArchive)
        .filter(SolutionArchive.problem == problem_id)
        .filter(SolutionArchive.user == user.index)
        .all()
    )

    # Do NIMBUS stuff here.

    ideal = problem.get_ideal_point()
    nadir = problem.get_nadir_point()
    if None in ideal or None in nadir:
        raise HTTPException(status_code=500, detail="Problem missing ideal or nadir value.")

    # If there are no solutions, generate a starting point for NIMBUS
    if not solutions:
        start_result = generate_starting_point(problem=problem)
        current_solution = SolutionArchive(
            user=user.index,
            problem=problem_id,
            method=method_id,
            decision_variables=list(start_result.optimal_variables.values()),
            objectives=list(start_result.optimal_objectives.values()),
            saved=False,
            current=True,
            chosen=False,
        )  # Maybe the database should be updated to use dicts
        # Save the generated starting point to the db
        db.add(current_solution)
        db.commit()
    else:
        # If there is a solution marked as current, use that. Otherwise just use the first solution in the db
        current_solution = next((sol for sol in solutions if sol.current), solutions[0])

    lower_bounds = []
    upper_bounds = []
    for i in range(len(problem.objectives)):
        if problem.objectives[i].maximize:
            lower_bounds[i] = nadir[problem.objectives[i].symbol]
            upper_bounds[i] = ideal[problem.objectives[i].symbol]
        else:
            lower_bounds[i] = ideal[problem.objectives[i].symbol]
            upper_bounds[i] = nadir[problem.objectives[i].symbol]

    # return FakeNIMBUSResponse(message="NIMBUS initialized.")
    return NIMBUSResponse(
        objective_symbols=[obj.symbol for obj in problem.objectives],
        objective_long_names=[obj.name for obj in problem.objectives],
        units=[obj.unit for obj in problem.objectives],
        is_maximized=[obj.maximize for obj in problem.objectives],
        lower_bounds=lower_bounds,
        upper_bounds=upper_bounds,
        previous_preference=current_solution.objectives,
        current_solutions=[current_solution.objectives],
        saved_solutions=[sol.objectives for sol in solutions if sol.saved],
        all_solutions=[sol.objectives for sol in solutions],
    )


@router.post("/iterate")
def iterate(
    request: NIMBUSIterateRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NIMBUSResponse | FakeNIMBUSResponse:
    """Iterate the NIMBUS algorithm.

    Args:
        request: The request body for a NIMBUS iteration.
        user (Annotated[User, Depends(get_current_user)]): The current user.
        db (Annotated[Session, Depends(get_db)]): The database session.

    Returns:
        The response from the NIMBUS algorithm.
    """
    # Do database stuff here.
    problem_id = request.problem_id
    method_id = request.method_id

    problem = db.query(ProblemInDB).filter(ProblemInDB.id == problem_id).first()
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found.")
    if problem.owner != user.index and problem.owner is not None:
        raise HTTPException(status_code=403, detail="Unauthorized to access chosen problem.")
    try:
        problem = Problem.model_validate(problem.value)
    except ValidationError:
        raise HTTPException(status_code=500, detail="Error in parsing the problem.") from ValidationError

    previous_solutions = (
        db.query(SolutionArchive)
        .filter(SolutionArchive.problem == problem_id, SolutionArchive.user == user.index)
        .all()
    )
    if not previous_solutions:
        raise HTTPException(status_code=404, detail="Problem not found in the database.")

    ideal = problem.get_ideal_point()
    nadir = problem.get_nadir_point()
    if None in ideal or None in nadir:
        raise HTTPException(status_code=500, detail="Problem missing ideal or nadir value.")

    # Do NIMBUS stuff here.
    results = solve_sub_problems(
        problem=problem,
        current_objectives=dict(zip(problem.objectives, request.reference_solution, strict=True)),
        reference_point=dict(zip(problem.objectives, request.preference, strict=True)),
        num_desired=request.num_solutions,
    )

    # See if the results include duplicates and remove them
    duplicate_indices = []
    for i in range(len(results) - 1):
        for j in range(i + 1, len(results)):
            if allclose(list(results[i].optimal_objectives.values()), list(results[i].optimal_objectives.values())):
                duplicate_indices.append(j)

    for index in sorted(duplicate_indices, reverse=True):
        results.pop(index)

    # Do database stuff again.
    # Save the given preferences
    pref = Preference(
        user=user.index, problem=problem_id, method=method_id, kind="NIMBUS", value=request.model_dump(mode="json")
    )
    db.add(pref)

    old_current_solutions = (
        db.query(SolutionArchive)
        .filter(SolutionArchive.problem == problem_id, SolutionArchive.user == user.index, SolutionArchive.current)
        .all()
    )

    # Mark all the old solutions as not current
    for old in old_current_solutions:
        old.current = False

    for res in results:
        # Check if the results already exist in the database
        for prev in previous_solutions:
            if allclose(res.optimal_objectives, prev.objectives):
                prev.current = True
                break
        # If the solution was not found in the database, add it
        if not prev.current:
            db.add(
                SolutionArchive(
                    user=user.index,
                    problem=problem_id,
                    method=method_id,
                    decision_variables=list(res.optimal_variables.values()),
                    objectives=list(res.optimal_objectives.values()),
                    saved=False,
                    current=True,
                    chosen=False,
                )
            )
    db.commit()

    solutions = (
        db.query(SolutionArchive)
        .filter(SolutionArchive.problem == problem_id, SolutionArchive.user == user.index)
        .all()
    )

    lower_bounds = []
    upper_bounds = []
    for i in range(len(problem.objectives)):
        if problem.objectives[i].maximize:
            lower_bounds[i] = nadir[problem.objectives[i].symbol]
            upper_bounds[i] = ideal[problem.objectives[i].symbol]
        else:
            lower_bounds[i] = ideal[problem.objectives[i].symbol]
            upper_bounds[i] = nadir[problem.objectives[i].symbol]

    return NIMBUSResponse(
        objective_symbols=[obj.symbol for obj in problem.objectives],
        objective_long_names=[obj.name for obj in problem.objectives],
        units=[obj.unit for obj in problem.objectives],
        is_maximized=[obj.maximize for obj in problem.objectives],
        lower_bounds=lower_bounds,
        upper_bounds=upper_bounds,
        previous_preference=request.preference,
        current_solutions=[sol.objectives for sol in solutions if sol.current],
        saved_solutions=[sol.objectives for sol in solutions if sol.saved],
        all_solutions=[sol.objectives for sol in solutions],
    )


@router.post("/intermediate")
def intermediate(
    request: NIMBUSIntermediateSolutionRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> NIMBUSResponse | FakeNIMBUSResponse:
    """Get solutions between two solutions using NIMBUS.

    Args:
        request: The request body for a NIMBUS iteration.
        user (Annotated[User, Depends(get_current_user)]): The current user.
        db (Annotated[Session, Depends(get_db)]): The database session.

    Returns:
        The response from the NIMBUS algorithm.
    """
    # Do database stuff here.
    problem_id = request.problem_id
    method_id = request.method_id

    problem = db.query(ProblemInDB).filter(ProblemInDB.id == problem_id).first()
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found.")
    if problem.owner != user.index and problem.owner is not None:
        raise HTTPException(status_code=403, detail="Unauthorized to access chosen problem.")
    try:
        problem = Problem.model_validate(problem.value)
    except ValidationError:
        raise HTTPException(status_code=500, detail="Error in parsing the problem.") from ValidationError

    previous_solutions = (
        db.query(SolutionArchive)
        .filter(SolutionArchive.problem == problem_id, SolutionArchive.user == user.index)
        .all()
    )
    if not previous_solutions:
        raise HTTPException(status_code=404, detail="Problem not found in the database.")

    ideal = problem.get_ideal_point()
    nadir = problem.get_nadir_point()
    if None in ideal or None in nadir:
        raise HTTPException(status_code=500, detail="Problem missing ideal or nadir value.")

    # Do NIMBUS stuff here.
    results = solve_intermediate_solutions(
        problem=problem,
        solution_1=dict(zip(problem.objectives, request.reference_solution_1, strict=True)),
        solution_2=dict(zip(problem.objectives, request.reference_solution_2, strict=True)),
        num_desired=request.num_solutions,
    )

    # See if the results include duplicates and remove them
    duplicate_indices = []
    for i in range(len(results) - 1):
        for j in range(i + 1, len(results)):
            if allclose(list(results[i].optimal_objectives.values()), list(results[i].optimal_objectives.values())):
                duplicate_indices.append(j)

    for index in sorted(duplicate_indices, reverse=True):
        results.pop(index)

    # Do database stuff again.
    # Save the given preferences
    pref = Preference(
        user=user.index,
        problem=problem_id,
        method=method_id,
        kind="NIMBUS_intermediate",
        value=request.model_dump(mode="json"),
    )
    db.add(pref)

    old_current_solutions = (
        db.query(SolutionArchive)
        .filter(SolutionArchive.problem == problem_id, SolutionArchive.user == user.index, SolutionArchive.current)
        .all()
    )

    # Mark all the old solutions as not current
    for old in old_current_solutions:
        old.current = False

    for res in results:
        # Check if the results already exist in the database
        for prev in previous_solutions:
            if allclose(res.optimal_objectives, prev.objectives):
                prev.current = True
                break
        # If the solution was not found in the database, add it
        if not prev.current:
            db.add(
                SolutionArchive(
                    user=user.index,
                    problem=problem_id,
                    method=method_id,
                    decision_variables=list(res.optimal_variables.values()),
                    objectives=list(res.optimal_objectives.values()),
                    saved=False,
                    current=True,
                    chosen=False,
                )
            )
    db.commit()

    solutions = (
        db.query(SolutionArchive)
        .filter(SolutionArchive.problem == problem_id, SolutionArchive.user == user.index)
        .all()
    )

    lower_bounds = []
    upper_bounds = []
    for i in range(len(problem.objectives)):
        if problem.objectives[i].maximize:
            lower_bounds[i] = nadir[problem.objectives[i].symbol]
            upper_bounds[i] = ideal[problem.objectives[i].symbol]
        else:
            lower_bounds[i] = ideal[problem.objectives[i].symbol]
            upper_bounds[i] = nadir[problem.objectives[i].symbol]

    return NIMBUSResponse(
        objective_symbols=[obj.symbol for obj in problem.objectives],
        objective_long_names=[obj.name for obj in problem.objectives],
        units=[obj.unit for obj in problem.objectives],
        is_maximized=[obj.maximize for obj in problem.objectives],
        lower_bounds=lower_bounds,
        upper_bounds=upper_bounds,
        previous_preference=request.preference,
        current_solutions=[sol.objectives for sol in solutions if sol.current],
        saved_solutions=[sol.objectives for sol in solutions if sol.saved],
        all_solutions=[sol.objectives for sol in solutions],
    )


@router.post("/save")
def save(request: SaveRequest) -> NIMBUSResponse | FakeNIMBUSResponse:
    """Save the solutions to the database.

    Args:
        request: The request body for saving solutions.

    Returns:
        The response from the NIMBUS algorithm.
    """
    # Do database stuff here.
    # Do NIMBUS stuff here.
    # Do database stuff again.
    return FakeNIMBUSResponse(message="Solutions saved.")


@router.post("/choose")
def choose(problem_id: int, solution: list[float]) -> NIMBUSResponse | FakeNIMBUSResponse:
    """Choose a solution as the final solution for NIMBUS.

    Args:
        problem_id: The ID of the problem to be solved.
        solution: The solution to be chosen.

    Returns:
        The response from the NIMBUS algorithm.
    """
    # Do database stuff here.
    # Do NIMBUS stuff here.
    # Do database stuff again.
    return FakeNIMBUSResponse(message="Solution chosen.")
