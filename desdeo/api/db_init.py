"""This module initializes the database."""
import warnings

import numpy as np
import polars as pl
from sqlalchemy_utils import create_database, database_exists, drop_database

from desdeo.api import db_models
from desdeo.api.db import SessionLocal, engine
from desdeo.api.routers.UserAuth import get_password_hash
from desdeo.api.schema import ObjectiveKind, ProblemKind, UserPrivileges, UserRole
from desdeo.problem.schema import DiscreteDefinition, Objective, Problem, Variable
from desdeo.problem.testproblems import binh_and_korn

TEST_USER = "test"
TEST_PASSWORD = "test"  # NOQA: S105 # TODO: Remove this line and create a proper user creation system.

# The following line creates the database and tables. This is not ideal, but it is simple for now.
# It recreates the tables every time the server starts. Any data saved in the database will be lost.
# TODO: Remove this line and create a proper database migration system.
print("Creating database tables.")
if not database_exists(engine.url):
    create_database(engine.url)
else:
    warnings.warn("Database already exists. Dropping and recreating it.", stacklevel=1)
    drop_database(engine.url)
    create_database(engine.url)
print("Database tables created.")

# Create the tables in the database.
db_models.Base.metadata.create_all(bind=engine)

# Create test users
db = SessionLocal()
user = db_models.User(
    username="test",
    password_hash=get_password_hash("test"),
    role=UserRole.ANALYST,
    privilages=[UserPrivileges.EDIT_USERS, UserPrivileges.CREATE_PROBLEMS],
    user_group="",
)
db.add(user)
db.commit()
db.refresh(user)
problem = binh_and_korn()

problem_in_db = db_models.Problem(
    owner=user.id,
    name="Binh and Korn",
    kind=ProblemKind.CONTINUOUS,
    obj_kind=ObjectiveKind.ANALYTICAL,
    value=problem.model_dump(mode="json"),
)
db.add(problem_in_db)
db.commit()


# db.close()


def fakeProblemDontLook():
    # Data loading
    data = pl.read_csv("./experiment/LUKE best front.csv")
    data = data.drop(["non_dominated", "source"])
    data = data * -1
    data = data.with_columns(pl.Series("index", np.arange(1, len(data) + 1)))
    # Problem definition

    index_var = Variable(
        name="index",
        symbol="index",
        initial_value=1,
        lowerbound=1,
        upperbound=len(data),
        variable_type="real",
    )

    npv = Objective(
        name="NPV",
        symbol="NPV",
        func=None,
        objective_type="data_based",
        maximize=True,
        ideal=data["npv4%"].max(),
        nadir=data["npv4%"].min(),
    )

    sv30 = Objective(
        name="SV30",
        symbol="SV30",
        func=None,
        objective_type="data_based",
        maximize=True,
        ideal=data["SV30"].max(),
        nadir=data["SV30"].min(),
    )

    removal1 = Objective(
        name="Removal1",
        symbol="Removal1",
        func=None,
        objective_type="data_based",
        maximize=True,
        ideal=data["removal1"].max(),
        nadir=data["removal1"].min(),
    )

    removal2 = Objective(
        name="Removal2",
        symbol="Removal2",
        func=None,
        objective_type="data_based",
        maximize=True,
        ideal=data["removal2"].max(),
        nadir=data["removal2"].min(),
    )

    removal3 = Objective(
        name="Removal3",
        symbol="Removal3",
        func=None,
        objective_type="data_based",
        maximize=True,
        ideal=data["removal3"].max(),
        nadir=data["removal3"].min(),
    )

    obj_data = {
        "NPV": data["npv4%"].to_list(),
        "SV30": data["SV30"].to_list(),
        "Removal1": data["removal1"].to_list(),
        "Removal2": data["removal2"].to_list(),
        "Removal3": data["removal3"].to_list(),
    }

    dis_def = DiscreteDefinition(
        variable_values={"index": data["index"].to_list()},
        objective_values=obj_data,
    )
    return Problem(
        name="LUKE Problem",
        description="None yet.",
        variables=[index_var],
        objectives=[npv, sv30, removal1, removal2, removal3],
        discrete_definition=dis_def,
    )


luke_problem = fakeProblemDontLook()

luke_problem_in_db = db_models.Problem(
    owner=user.id,
    name="LUKE Problem",
    kind=ProblemKind.DISCRETE,
    obj_kind=ObjectiveKind.ANALYTICAL,
    value=luke_problem.model_dump(mode="json"),
)
db.add(luke_problem_in_db)
db.commit()
db.close()
