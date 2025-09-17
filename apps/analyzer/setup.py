from setuptools import setup, find_packages

setup(
    name="chessbot-analyzer",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "pydantic>=1.10,<2",
        "python-chess>=1.999",
        "typer[all]>=0.9.0",
        "loguru>=0.7.0",
        "psycopg2-binary>=2.9.0",
        "sqlalchemy>=1.4.0",
        "requests>=2.28.0",
        "python-dotenv>=1.0.0",
        "zstandard>=0.22.0",
        "tqdm>=4.66.0",
        "orjson>=3.9.0",
    ],
    entry_points={
        "console_scripts": [
            "chessbot=chessbot_analyzer.cli:app",
        ],
    },
)
