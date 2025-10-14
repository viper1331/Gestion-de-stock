from setuptools import setup

# Configuration pour générer un installateur Windows (setup.exe)
# Utiliser :
#   pip install setuptools
#   python setup.py bdist_wininst

setup(
    name='GestionStock',
    version='1.0',
    description="Application de gestion de stock - Sebastien Cangemi",
    author='Sebastien Cangemi',
    author_email='contact@example.com',
    url='https://example.com/GestionStock',
    scripts=['gestion_stock.py'],
    options={
        'bdist_wininst': {
            'install_icon': None,  # Chemin vers un fichier .ico si vous en avez
            'bitmap': None,        # Chemin vers un bitmap pour la fenêtre d'installation
            'title': 'GestionStock Installer'
        }
    },
    classifiers=[
        'Programming Language :: Python :: 3',
        'Operating System :: Microsoft :: Windows',
    ],
)
