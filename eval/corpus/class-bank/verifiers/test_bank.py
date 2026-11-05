from solution import BankAccount
import pytest

def test_deposit():
    a = BankAccount(10); a.deposit(5); assert a.balance == 15
def test_withdraw():
    a = BankAccount(10); a.withdraw(4); assert a.balance == 6
def test_overdraft():
    a = BankAccount(10)
    with pytest.raises(ValueError): a.withdraw(20)
    assert a.balance == 10
def test_negative_deposit():
    a = BankAccount(10)
    with pytest.raises(ValueError): a.deposit(-5)
