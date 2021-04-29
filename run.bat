start python server.py
FOR /L %%A IN (1,1,500) DO (
  start cmd /k python client.py
)
