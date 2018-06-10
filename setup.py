from setuptools import find_packages, setup
setup(
name="dss_ui",
    version="0.1",
    description="",
    author="Galen Curwen-McAdams",
    author_email='',
    platforms=["any"],
    license="Mozilla Public License 2.0 (MPL 2.0)",
    include_package_data=True,
    data_files = [("", ["LICENSE.txt"])],
    url="",
    packages=find_packages(),
    install_requires=['kivy', 'ma_cli', 'ma_wip', 'lings'],
    dependency_links=["https://github.com/galencm/ma-cli/tarball/master#egg=ma_cli-0.1",
                      "https://github.com/galencm/machinic-wip/tarball/master#egg=ma_wip-0.1",
                      "https://github.com/galencm/machinic-lings/tarball/master#egg=lings-0.1"],
    entry_points = {'console_scripts': ['ma-ui-dss = dss_ui.dss_ui:main',
                                        'dss-ui = dss_ui.dss_ui:main',
                                       ],
                            },
)
