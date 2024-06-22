
import numpy as np
import pandas as pd

s = pd.Series([1, 3, 5, np.nan, 6, 8])

dates = pd.date_range("20130101", periods=6)

df = pd.DataFrame(np.random.randn(6,4), index=dates, columns=list("ABCD"))

s2 = pd.Series([1, 3, 5, np.nan, 6, 8], index=dates)

s2['20130102']

df['A']['20130102']

