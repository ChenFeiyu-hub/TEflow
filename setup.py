"""Bundle the same runtime recipes in wheels; no copied recipes in the source tree."""
from pathlib import Path
from setuptools import setup
from setuptools.command.build_py import build_py


class BuildWithRecipes(build_py):
    def recipe_mapping(self):
        mapping = {}
        for folder in ("workflow", "scripts", "envs"):
            for path in sorted(Path(folder).rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
                    mapping[str(Path(self.build_lib) / "teflow" / "_assets" / path)] = str(path)
        return mapping

    def run(self):
        super().run()
        if not self.editable_mode:
            for destination, source in self.recipe_mapping().items():
                self.mkpath(str(Path(destination).parent))
                self.copy_file(source, destination)

    def get_outputs(self, include_bytecode=1):
        return super().get_outputs(include_bytecode) + list(self.recipe_mapping())

    def get_output_mapping(self):
        return dict(super().get_output_mapping(), **self.recipe_mapping())

    def get_source_files(self):
        return super().get_source_files() + list(self.recipe_mapping().values())


setup(cmdclass={"build_py": BuildWithRecipes})
