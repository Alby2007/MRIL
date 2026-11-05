from solution import merge_intervals

def test_overlap(): assert merge_intervals([[1,3],[2,6],[8,10]]) == [[1,6],[8,10]]
def test_touching(): assert merge_intervals([[1,4],[4,5]]) == [[1,5]]
def test_nested(): assert merge_intervals([[1,10],[2,3]]) == [[1,10]]
def test_unsorted(): assert merge_intervals([[5,7],[1,3]]) == [[1,3],[5,7]]
def test_empty(): assert merge_intervals([]) == []
