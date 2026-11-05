write a web application for managing a round robin pickleball tournament.
Some of the variables:
* number of courts. 4 players to a court
* list of players - should be able to import a csv of names and emails and then a page to select who is playing today
* number of rounds to play

After each round the score of the game is reported.  Each player gets the number of points their team scores and their individual score is updated
After the scores are reported then show the list of players from most points to least
At the end of all the rounds the players are listed from most to least points

The teams will change each round and ideally any two players would only be partners once during the tournament, although this may not be possible if the number of players is small.  We also want to maximize the variety of the people played against so we don't want the same four players just rotating through partners and playing each other.

A simple database like sqlite is fine to keep track of the scores
