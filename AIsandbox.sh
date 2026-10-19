#!/bin/bash


if
 test $# -eq 0
then
 #firefox https://openrouter.ai/activity &
 firefox https://openrouter.ai/activity?date_preset=past_1_year &
fi

# ~/apps/sandbox-code/sandbox-code --x11 $@
#~/apps/sandbox-code-atrent/sandbox-code --blacklist --no-git --x11 $@    #|& tee .sandbox-code.log
script --quiet --append .sandbox-code.log -- ~/apps/sandbox-code-atrent/sandbox-code --blacklist --no-git $@
