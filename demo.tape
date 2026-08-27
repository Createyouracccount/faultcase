Output demo.gif
Output demo.mp4

Set FontSize 15
Set Width 1180
Set Height 660
Set Padding 14
Set TypingSpeed 25ms

Hide
Type "cd samples/gc2-sample && clear"
Enter
Show

Type `# A customer ticket: "Your 502s crash our retry config. Your bug or ours?"`
Enter
Sleep 1.5s
Type "head -9 original_ticket/customer_ticket.md"
Enter
Sleep 3.5s

Type "# faultcase turned that ticket into a runnable repro bundle:"
Enter
Type "find repro fix -type f | sort"
Enter
Sleep 3s

Type "# 1) reproduce the customer's exact crash (offline, --network none):"
Enter
Type "docker run --rm --network none faultcase-demo; echo exit=$?"
Enter
Sleep 5s

Type "# 2) the fix is one line:"
Enter
Type "cat fix/candidate.patch"
Enter
Sleep 3.5s

Type "# 3) machine evidence - 3x fail pre-patch (signature matched), 3x pass post-patch:"
Enter
Type "faultcase-verify . --runner venv"
Enter
Sleep 16s

Type "# ticket in -> verified repro bundle out.   pip install faultcase"
Enter
Sleep 3.5s
