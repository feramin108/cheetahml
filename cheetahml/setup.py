from setuptools import setup, find_packages

setup(
    name='cheetah',
    version='0.1.1',
    packages=find_packages(),
    py_modules=['base', 'routes'],
    package_data={'cheetah.shared_utils.configurator': ['default.ini']},

    install_requires=[
        'celery==5.3.6',
        'colorlog==6.8.2',
        'fastapi==0.103.2',
        'google==3.0.0',
        'grpcio==1.60.1',
        'grpcio-tools==1.60.1',
        'logger==1.4',
        'redis==5.0.1',
        'prometheus-fastapi-instrumentator==6.1.0',
        'prometheus_client==0.20.0',
        'protobuf==4.25.2',
        'pydantic==2.3.0',
        'py-grpc-prometheus==0.7.0',
        'uvicorn==0.23.2',
    ]
)
