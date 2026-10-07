"""Decide what each file is: source, test, config, fixture, doc, generated, ..."""

import posixpath

from . import globs

LANG_BY_EXT = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".vue": "javascript", ".svelte": "javascript",
    ".go": "go", ".java": "java", ".kt": "kotlin", ".kts": "kotlin", ".scala": "scala",
    ".rb": "ruby", ".rs": "rust", ".cs": "csharp", ".php": "php", ".swift": "swift",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".m": "objc", ".mm": "objc", ".dart": "dart", ".ex": "elixir", ".exs": "elixir",
    ".sh": "shell", ".bash": "shell", ".sql": "sql", ".lua": "lua", ".r": "r", ".R": "r",
}
CONFIG_LANG = {".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".json": "json", ".ini": "ini", ".cfg": "ini",
               ".env": "env", ".properties": "ini", ".conf": "ini"}

# Checked in this order; the first kind with a matching pattern wins.
DEFAULT_RULES = [
    ("generated", [
        "**/node_modules/**", "**/vendor/**", "**/dist/**", "**/build/**", "**/.next/**", "**/target/**",
        "**/*.min.js", "**/*.min.css", "**/*.map", "**/*_pb2.py", "**/*_pb2_grpc.py", "**/*.pb.go",
        "**/*.generated.*", "**/*.lock", "**/package-lock.json", "**/pnpm-lock.yaml", "**/yarn.lock",
        "**/go.sum", "**/__generated__/**", "**/migrations/**", "**/alembic/versions/**",
    ]),
    ("atlas", [".project-map/**"]),
    ("example", ["**/examples/**", "**/example/**", "**/samples/**", "**/sample/**", "**/demos/**"]),
    ("i18n", ["**/locale/**", "**/locales/**", "**/translations/**", "**/i18n/*.json", "**/*.po", "**/*.mo"]),
    ("fixture", ["**/fixtures/**", "**/testdata/**", "**/__snapshots__/**", "**/*.snap", "**/cassettes/**"]),
    ("test", [
        "**/test_*.py", "**/*_test.py", "**/conftest.py", "**/tests/**", "**/test/**", "**/__tests__/**",
        "**/*.test.*", "**/*.spec.*", "**/*_test.go", "**/spec/**", "**/*Test.java", "**/*Tests.cs",
    ]),
    ("doc", ["**/*.md", "**/*.mdx", "**/*.rst", "**/*.adoc", "docs/**", "**/LICENSE*", "**/CHANGELOG*"]),
    ("manifest", [
        "**/pyproject.toml", "**/setup.py", "**/setup.cfg", "**/requirements*.txt", "**/Pipfile",
        "**/package.json", "**/go.mod", "**/Cargo.toml", "**/Gemfile", "**/pom.xml", "**/build.gradle*",
        "**/tsconfig*.json", "**/*.csproj",
    ]),
    ("ci", [".github/**", ".gitlab-ci.yml", ".circleci/**", ".devcontainer/**", ".vscode/**", ".idea/**",
            "**/Dockerfile*", "**/docker-compose*.y*ml", "**/Makefile", "**/CODEOWNERS",
            "**/.pre-commit-config.yaml", "**/.readthedocs.y*ml", "**/mkdocs.y*ml", "**/codecov.y*ml", "**/.codecov.y*ml",
            "**/tox.ini", "**/.flake8", "**/.pylintrc", "**/mypy.ini", "**/pytest.ini", "**/.coveragerc", "**/.editorconfig",
            "**/.eslintrc*", "**/.prettierrc*", "**/.babelrc*", "**/.stylelintrc*", "**/.nycrc*", "**/.mocharc*",
            "**/jest.config.*", "**/vitest.config.*", "**/.markdownlint*", "**/renovate.json", "**/.renovaterc*",
            "**/dependabot.y*ml", "**/netlify.toml", "**/vercel.json", "**/.yamllint*", "**/.golangci.y*ml"]),
    ("config", [
        "**/*.yaml", "**/*.yml", "**/*.toml", "**/*.ini", "**/*.cfg", "**/*.properties", "**/*.conf",
        "**/.env", "**/.env.*", "**/*.env",
        "**/config/**/*.json", "**/configs/**/*.json", "**/settings/**/*.json", "**/conf/**/*.json",
        "**/*config*.json", "**/*settings*.json",
    ]),
]


def lang_of(path):
    ext = posixpath.splitext(path)[1]
    if ext in LANG_BY_EXT:
        return LANG_BY_EXT[ext]
    base = posixpath.basename(path)
    if base.startswith(".env") or base.endswith(".env"):
        return "env"
    return CONFIG_LANG.get(ext)


def is_code(path):
    return posixpath.splitext(path)[1] in LANG_BY_EXT


class Classifier:
    """settings: {"include": [...], "exclude": [...], "classify": {kind: [patterns]}}"""

    def __init__(self, settings=None):
        settings = settings or {}
        self.include = settings.get("include") or []
        self.exclude = settings.get("exclude") or []
        self.overrides = list((settings.get("classify") or {}).items())

    def __call__(self, path):
        """(kind, lang), or (None, None) when the file is excluded from analysis."""
        if self.include and not globs.match_any(path, self.include):
            return None, None
        if globs.match_any(path, self.exclude):
            return None, None
        lang = lang_of(path)
        for kind, patterns in self.overrides:
            if globs.match_any(path, patterns):
                return kind, lang
        for kind, patterns in DEFAULT_RULES:
            if not globs.match_any(path, patterns):
                continue
            if kind == "test":
                return ("test", lang) if is_code(path) else ("fixture", lang)
            if kind == "config" and is_code(path):
                continue
            return kind, lang
        if is_code(path):
            return "source", lang
        return "other", lang
