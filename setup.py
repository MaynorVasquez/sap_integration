from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

with open("dev-requirements.txt", "w") as f:
    f.write("unittest2\ncoverage\n")

setup(
    name="sap_integration",
    version="0.0.1",
    description="SAP Integration for ERPNext",
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    install_requires=install_requires,
    tests_require=["unittest2", "coverage"],
    test_suite="sap_integration.tests",
)