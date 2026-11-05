from solution import TextBuffer


def test_write_and_contents():
    b = TextBuffer()
    b.write('hello')
    b.write(' world')
    assert b.contents() == 'hello world'


def test_delete():
    b = TextBuffer()
    b.write('abcdef')
    b.delete(2)
    assert b.contents() == 'abcd'


def test_undo_write():
    b = TextBuffer()
    b.write('abc')
    b.undo()
    assert b.contents() == ''


def test_undo_delete():
    b = TextBuffer()
    b.write('abcdef')
    b.delete(2)
    b.undo()
    assert b.contents() == 'abcdef'


def test_undo_past_beginning_noop():
    b = TextBuffer()
    b.undo()
    b.write('x')
    b.undo()
    b.undo()
    assert b.contents() == ''
