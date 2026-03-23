from pydantic import BaseModel, ConfigDict
from pydantic.fields import Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectSection(StrictModel):
    name: str
    version: str = Field(default="0.0.0")
    description: str = Field(default="")
    readme: str = Field(default="README.md")
    licence: str = Field(default="MIT")
    dependencies: list[str] = Field(default=["git@https://github.com/encore-language/stdlib"])


class ProjectManifest(StrictModel):
    project: ProjectSection

    @staticmethod
    def default_filename() -> str:
        return "encore.toml"

    def get_project_name(self) -> str:
        return self.project.name

    @classmethod
    def default(cls, project_name: str) -> "ProjectManifest":
        return cls(
            project=ProjectSection(name=project_name),
            special=SpecialSection(),
        )
