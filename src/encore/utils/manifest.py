import tomllib
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from pydantic.fields import Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectTarget(StrEnum):
    AUTO = "auto"
    EXECUTABLE = "executable"
    STATIC_LIB = "static_lib"
    SHARED_LIB = "shared_lib"


class ProjectSection(StrictModel):
    name: str
    target: str = Field(default=ProjectTarget.AUTO.value)
    version: str = Field(default="0.0.0")
    description: str = Field(default="")
    readme: str = Field(default="README.md")
    licence: str = Field(default="MIT")
    dependencies: list[str] = Field(default=[])


class NativeLibrarySection(StrictModel):
    name: str
    kind: str = Field(default="system")
    link_name: str | None = None
    path: str | None = None
    search_paths: list[str] = Field(default=[])
    frameworks: list[str] = Field(default=[])
    link_args: list[str] = Field(default=[])
    cfg: str | None = None


class NativeSection(StrictModel):
    libraries: list[str | NativeLibrarySection] = Field(default=[])
    search_paths: list[str] = Field(default=[])
    frameworks: list[str] = Field(default=[])
    link_args: list[str] = Field(default=[])


class ProjectManifest(StrictModel):
    project: ProjectSection
    native: NativeSection = Field(default_factory=NativeSection)

    @staticmethod
    def default_filename() -> str:
        return "encore.toml"

    def get_project_name(self) -> str:
        return self.project.name

    @classmethod
    def default(cls, project_name: str) -> "ProjectManifest":
        return cls(
            project=ProjectSection(name=project_name),
        )

    @classmethod
    def read(cls, path: Path) -> "ProjectManifest":
        with path.open("rb") as f:
            data = tomllib.load(f)
        return cls(**data)
