start python server.py
FOR /L %%A IN (1,1,5) DO (
  start cmd /k python client.py
)
