"""Tests for the shared discipline classifier."""
from app.classify import classify
from app.models import Discipline


def test_specific_before_broad():
    # "stage rally" and "comp safari" must win over the broad "rally"/"safari"
    assert classify("Epynt Stage Rally") is Discipline.RALLY
    assert classify("AWDC Comp Safari R1") is Discipline.OFF_ROAD


def test_trials_family():
    assert classify("Tyro & RTVT") is Discipline.TRIALS
    assert classify("Weston Coyney RTV Trial") is Discipline.TRIALS
    assert classify("August PCA") is Discipline.TRIALS
    assert classify("Sporting Trial") is Discipline.TRIALS


def test_off_road():
    assert classify("Eckington CCVT") is Discipline.OFF_ROAD
    assert classify("Cross Country Vehicle Event") is Discipline.OFF_ROAD
    assert classify("Winch Challenge") is Discipline.OFF_ROAD


def test_hillclimb_and_speed():
    assert classify("Prescott Hill Climb") is Discipline.HILLCLIMB
    assert classify("Loton Park Hillclimb") is Discipline.HILLCLIMB
    assert classify("BARC Wales Autumn Sprint") is Discipline.HILLCLIMB


def test_rally():
    assert classify("Wyedean Rally") is Discipline.RALLY
    assert classify("British Rallycross Championship") is Discipline.RALLY
    assert classify("Targa Rally") is Discipline.RALLY


def test_autotest_is_other():
    assert classify("Thruxton AutoSOLO") is Discipline.OTHER
    assert classify("Club Autotest") is Discipline.OTHER


def test_unknown_is_other():
    assert classify("Supercar Sunday") is Discipline.OTHER
    assert classify("") is Discipline.OTHER
    assert classify("Christmas Meal") is Discipline.OTHER
