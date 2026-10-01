from setuptools import setup

setup(
    name="studyflow",
    version="1.0.0",
    py_modules=["study_timer", "main"],
    install_requires=[
        "PyQt5>=5.15.0",
    ],
    entry_points={
        "console_scripts": [
            "studyflow=study_timer:main",
        ],
    },
)
