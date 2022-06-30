import setuptools
import glob
import gupshup_matrix

try:
    long_desc = open("README.md").read()
except IOError:
    long_desc = "Failed to read README.md"

setuptools.setup(
    name="gupshup-matrix",
    version=gupshup_matrix.__version__,
    url="https://gitlab.com/iKono/ikono-grupshup-bridge",

    author="Hector Ramirez",
    author_email="hramirez@ikono.com.co",

    description="A Matrix-Gupshup relaybot bridge.",
    long_description=long_desc,
    long_description_content_type="text/markdown",

    packages=setuptools.find_packages(),

    install_requires=[
        "aiohttp>=3.0.1,<4",
        "mautrix>=0.5.5,<0.6",
        "ruamel.yaml>=0.15.94,<0.16.0",
        "commonmark>=0.8,<0.10",
        "python-magic>=0.4,<0.5",
        "SQLAlchemy>=1.2,<2",
        "alembic>=1,<2",
    ],
    extras_require={
        "phonenumbers": ["phonenumbers>=8,<9"],
        "psycopg2": ["psycopg2>=2.8.5"],
    },

    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)",
        "Topic :: Communications :: Chat",
        "Framework :: AsyncIO",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
    ],
    entry_points="""
        [console_scripts]
        gupshup-matrix=gupshup_matrix.__main__:main
    """,
    data_files=[
        (".", ["gupshup_matrix/example-config.yaml", "alembic.ini"]),
        ("alembic", ["alembic/env.py"]),
        ("alembic/versions", glob.glob("alembic/versions/*.py"))
    ],
)
