import tomllib
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic.fields import Field

from encore import CORE_PATH


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectSection(StrictModel):
    name: str
    version: str = Field(default="0.0.0")
    description: str = Field(default="")
    readme: str = Field(default="README.md")
    licence: str = Field(default="MIT")
    dependencies: list[str] = Field(default=[])
    build: str | None = Field(default=None)


class ProjectManifest(StrictModel):
    project: ProjectSection

    @staticmethod
    def default_filename() -> str:
        return "encore.toml"

    def get_project_name(self) -> str:
        return self.project.name

    @classmethod
    def default(cls, project_name: str) -> Self:
        return cls(project=ProjectSection(name=project_name))

    @classmethod
    def read(cls, path: Path) -> Self:
        with path.open("rb") as f:
            data = tomllib.load(f)

        try:
            result = cls(**data)
        except ValidationError as e:
            print(f"Validation error in manifest {path}:\n{e}")
            exit(-1)

        # Inject libcore
        libcore = "sys@core"
        if libcore not in result.project.dependencies and path.parent != CORE_PATH:
            result.project.dependencies.append(libcore)

        return result

    @classmethod
    def read_with_default_filename(cls, root: Path) -> Self:
        return cls.read(root / cls.default_filename())
