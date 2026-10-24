from setuptools import setup, find_packages

setup(
    name="ubuntu-sysperf-cli",
    version="3.1.0",
    description="A gradient-themed, real-time Ubuntu system performance dashboard for the terminal, with GPU/battery panels, sortable/filterable processes, and JSON/CSV export",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=["psutil>=5.9.0", "rich>=13.7.0"],
    entry_points={"console_scripts": ["sysperf=sysperf.main:main"]},
)
