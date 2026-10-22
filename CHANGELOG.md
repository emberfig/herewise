# Changelog

What changed in each release of Herewise, for the people who use it. The decisions behind these
changes, with their evidence, are in `docs/DECISIONS-AND-LESSONS.md`.

Every release names the files it is made of and their SHA-256 checksums, in `SHA256SUMS.txt`
beside the download. Check one before running it:

```powershell
Get-FileHash .\Herewise-Setup-0.1.18.exe -Algorithm SHA256
```

## 0.1.18

- **Reopen attendance for the students who missed it.** A class taken live and ended can be opened
  again, the same day, from the Attendance taken page or its class register. Whoever has not
  scanned can scan; everyone present stays present, and corrections and excused absences stay as
  they were. While it is open nobody is absent and it counts towards nothing, as at Start. End it
  again and whoever still has not scanned is absent again. A scan made between the End and the
  reopening does not count, so anyone who scanned then scans again. It needs the permission to
  correct attendance, so a course rep asks for corrections instead. The activity log records the
  reopening and the second end, with how many more came in.
- **Light and dark.** Choose System, Light or Dark from your name at the top of any screen, in
  Settings, or when setting Herewise up. System follows Windows, as before. The choice is kept for
  this computer, not in the register, so downloading your data or restoring a backup does not carry
  it, and it is applied before the window draws anything, so a dark screen never opens on a light
  frame. Exported PDFs and Excel files look the same whichever you choose.

## 0.1.17

- **Herewise is free software.** It is licensed under the GNU General Public License, version 2 or
  any later version, and this release is distributed under version 3. Its source is published
  beside the installer as `Herewise-0.1.17-source.zip`, with its checksum in `SHA256SUMS.txt`.
  About says so, and the licence texts travel in the program's `licences` folder.
- **Pick students into groups by hand.** On a course's Groups tab, make empty groups, tick students
  and put them in a group (or in no group). Each is a move from today. This was already on the
  lecturer's laptop in a build numbered 0.1.16 that the 0.1.16 notes did not list; this release
  gives it its own number, so the two 0.1.16 builds can no longer be mixed up.
- **Removing a student from a course says what it does.** The dialog and the Removed list said
  classes before the removal still count. They do not: the student comes off the course's register,
  sheet and eligibility list for every class, past ones included. Nothing changed in what removal
  does; the words now match it. Their scans are kept, and Add students puts them back.

## 0.1.16

- **Herewise sets up the Ethernet for the terminal.** When the Connection check finds this
  computer's Ethernet is not on the terminal's network, Set it up asks Windows once and adds
  192.168.1.100 beside the address it already has, with a route so a Wi-Fi on the same numbers
  cannot take the terminal's traffic. Say No and the steps by hand are shown. Take it off again
  from the same place. Offered in first-run setup too.
- **A course can be taken in groups.** On a course's new Groups tab, split its students into Group A,
  B, C and D (or any number from 2 to 20), move a student, or paste the department's own list into
  a group. Other courses keep their whole roster.
- **A class is for everybody or for one group.** Start taking attendance on a course with groups asks
  who the class is for, with nothing chosen. A student is counted only against the classes for
  everybody and their own group's, so nobody is absent from another group's practical, and each
  student's percentage and "classes left" are their own.
- **Moving a student keeps their history.** Changing group from today keeps the classes already had
  with the old group; "in the wrong group all along" changes the whole stretch.
- **One sheet per group.** The Sheet tab has a group switcher. A box for a class the student was not
  in the group for is shaded with a diagonal and counts neither way. Export one group's sheet, or
  every group in one file: a section of pages per group in the PDF, a worksheet per group in Excel.
- **The Classes tab says who each class was for**, and a class given to the wrong group can be
  changed. Classes found in the scans go to a group when three quarters of those who scanned were in
  it. A register lists students from another group who scanned in it, without counting them.

## 0.1.15

- **Take a student off a course from the sheet.** Click their name on the attendance sheet and choose
  Remove from this course. It is the same as Remove on the course's Students tab: it asks why, keeps
  their attendance so far, and leaves them on their level and on the terminal. Add students puts
  them back.

## 0.1.14

What importing a roster does with the wrong file, a file in an unexpected shape, and the wrong list.
Every real roster reads exactly as before.

- **When Herewise cannot tell which column is which, it asks.** It shows the first rows of the file
  with its best guess (the matric number here, the name there, the first student on this row) and
  you correct it and press Preview. This covers headings it does not recognise, a matric number
  column that holds names, and a workbook with several lists and none named for the level.
- **More layouts are read without asking:** surname and other names in columns of their own (or
  first and middle names), lists separated by tabs or semicolons, Excel's "Unicode Text", and a
  workbook with a cover page in front of the list.
- **Another level's list needs a tick.** Importing 300 Level's students into 200 Level says so at the
  top and waits for "Yes, move them to 200 Level" before the Import button works.
- **A file with most of its rows refused needs a tick** before the rest go in.
- **A total or a note under the list is refused**, rather than imported as a student with no matric
  number. So is a matric number with no number in it, with what to type instead.
- **A file that is not a roster says what it is:** a PDF, a photo, a Word or PowerPoint file, a
  LibreOffice spreadsheet, a zip folder, or a workbook locked with a password (with how to unlock it).
  Anything over 5 MB is turned away as not a roster.
- **Headings with nobody under them say so**, instead of "Nothing in this file is new".
- **Download a blank template**, named for the level, beside the file on both imports.
- **A refused file stays on screen** beside it until you choose another. It was a message that
  disappeared after six seconds.

## 0.1.13

What importing a department's real rosters found.

- **Importing a roster no longer makes a course.** Importing four levels made four courses called
  200 Level to 500 Level that nobody asked for. Make each course with New course and its real code:
  everybody on its level joins it, and so does anybody imported into that level later. A course the
  import made records nothing until a class is held on it, so Delete on its card removes it.
- **The terminal chip no longer swaps between "not reachable" and "Something else is using the
  terminal"** while the cable is out. Each check waited thirty seconds for an unplugged terminal and
  the next began after twenty, so it found the first still waiting. A check now gives up after two
  seconds, and one never starts while another is running.
- **The banner about the terminal has one full stop.** It read "192.168.1.201:4370.. Nothing can be
  sent".
- **The chip at the top says Device not reachable**, and the banner under it gives the address. The
  chip carried the whole sentence, which pushed your name onto two lines.

## 0.1.12

What a full audit before installing found. Nothing here changes what is recorded; it changes what
using the app from the keyboard, and removing it, are like.

- **The student search at the top keeps what you type.** It was cleared every twenty seconds, when
  Herewise checked the terminal, and the cursor went with it.
- **Pressing Save, Start or any button that works for a moment keeps your place.** From the keyboard,
  focus used to jump to the top of the page, and closing the dialog that followed left you there.
  Ending attendance, cancelling a class and deleting something now leave focus on the screen.
- **A form with a mistake takes you to it.** Pressing Continue or Save with a field wrong now puts the
  cursor in the first field to fix, and a screen reader reads out what is wrong.
- **Save stays greyed out once saved** on Settings, a course's figures and Sheet setup. It was
  pressable again straight after saving.
- **Setting up a new computer says when the terminal still holds old scans**, and to clear them from
  Device before importing a roster, so none is read as a new student's. It used to call such a
  terminal "empty and ready".
- **A terminal that does not answer is said plainly** when deleting a roster or saving a keypad
  password. It used to appear under what you had typed, as though that were wrong.
- **The connection check says what it is doing** during the few seconds it waits with the cable out.
- **Removing Herewise while it is open is refused**, in every way of removing it. A quiet removal used
  to take the shortcuts and the Installed apps entry and leave the program folder behind.

## 0.1.11

- **Enrolment no longer calls an empty level enrolled.** A level with nobody on it said "100 Level
  is enrolled: every student on this level has two fingers", over a list that said No student
  matches "". It now says nobody is on the level yet, with Import roster, and the level list marks
  empty levels "no students yet".

## 0.1.10

- **Clear the scans works again after a roster is deleted.** It refused with "15 scans could not be
  confirmed as stored". Those scans belonged to the deleted roster, which a pull leaves out on
  purpose, and the check before clearing counted them as missing. They count as accounted for now,
  and the result says how many were from the deleted roster. A scan that really was not stored still
  stops the clear.

## 0.1.9

Direct-entry students are DE.

- **A student with no matric number yet reads DE**, for direct entry, everywhere a matric number is
  shown: the sheet, class registers, the student lists, and every PDF and spreadsheet export. It used
  to read "no matric yet" on the sheet and be blank elsewhere.
- **DE can be typed in a roster**, in the matric number column, and so can "D.E." or "Direct entry".
  Each one is a student with no number yet, not a shared number, so a list with twenty-four of them
  imports all twenty-four. When the real number comes, add it from the sheet by pressing DE.

## 0.1.8

What testing 0.1.7 on the real terminal found.

- **The first scan after Start now counts.** Starting a class sets the terminal's clock, and it was
  setting it about ten seconds slow, so every scan was stamped ten seconds early and a scan made
  straight after Start was dated before the class began. Seen on three classes in a row. The clock
  is now set at the moment it is written, checked, and set again if it is still out, and the class
  opens on the terminal's own clock.
- **Cancelling a class that is taking attendance stops it.** It used to stay open: the banner went on
  saying it was taking attendance, and another class could not start until somebody pressed End.
- **Cancel and Restore show at once.** The class register drew a second copy of itself below the
  first, so the page you were looking at did not change.
- **The class register updates as students scan**, every few seconds while the class is open: the
  counts, each student's status and the time they scanned. A search or filter you have set stays.

## 0.1.7

Set Herewise up on one computer and take all its data to another.

- **Download your data**, first in Settings: everything in the register in one file, the students,
  courses, classes, scans and corrections. Keep it as a backup, or carry it to another computer on a
  USB stick. The file is called `herewise-data-<date>-<time>.db`.
- **Already used Herewise? Import your data**, at the top of the first screen on a new computer.
  Choose the file, see what it holds (students, courses, classes, scans, the terminal it uses), then
  make your own account. Only the data comes across.
- **Accounts and passwords stay on the old computer.** The old accounts are brought across switched
  off, with no password, because every correction and class still says who made it. Nobody can
  sign in with them. The new owner can switch one back on from Accounts and give it a new password.
- You can choose the same username you had before. The old account with that name is renamed, for
  example `lecturer-previous`.
- This works only on a computer where nobody has made an account yet. To replace a register that
  is already in use, sign in and use Settings, Backup, Restore.
- The installer recognises an existing Herewise from its own folder, so it offers Update even when
  Windows has lost Herewise's entry in Installed apps, and puts the entry back.

## 0.1.6

A level's roster can be deleted, with everything on it.

- **Delete roster**, on the Levels screen, for any level with something on it. It deletes the
  level's students, its courses, their classes, the scans, corrections and excused absences, and
  the roster imports. It asks you to type the level's name first and lists what will go.
- **The students and their fingerprints come off the terminal first.** If the terminal does not
  answer, nothing is deleted: switch it on, check it answers on the Device screen, and press Delete
  roster again. Removing an empty level also needs the terminal, and takes anybody left on it with
  that level's IDs.
- The level stays, empty, ready for a new roster. The old device IDs are not given out again, so a
  scan left in the terminal's own log can never become a new student's. Reading the scans later
  leaves those out and says how many.
- A copy of the register is saved in Backups just before anything is deleted.

### A proper installer

- **The installer has its own window** now, in Herewise's colours and type, instead of two plain
  Windows message boxes. It says where the program goes and that your register is left alone,
  offers a desktop shortcut, shows each step with a real progress bar, and ends with Open Herewise.
- **Updating says what it is updating from**, such as "From 0.1.5 to 0.1.6".
- **If Herewise is open**, the installer says so and offers to close it and carry on. Herewise saves
  every change as it happens, so nothing is lost.
- **Removing Herewise** from Installed apps uses the same window, and says where your register is
  kept. The program folder now always goes: it used to stay behind if the closing message was left
  on the screen for more than two seconds.
- Installing for several machines with `--quiet` works exactly as before.

### Fewer settings

Seven settings are gone from Settings, because taking attendance with Start and End made them
pointless. Each keeps the value it had by default:

- Grace before a class (15 minutes) and after it (30 minutes). A class you start and end counts
  exactly the minutes it was open, so these only touch a class found later in the terminal's scans.
- Work classes out automatically (still on), Students that make a class (5) and Gap that ends a
  class (90 minutes), which are how a class taken without the laptop is found in the scans.
- Days a reminder waits (7).
- Where attendance usually comes from, which nothing in Herewise read.

## 0.1.5

Which week a class goes in is your choice now, weeks can be removed and added, and students without
a matric number yet can be taken and given one later.

### Which week

- **Every class asks which week it is for.** Start taking attendance asks "Which week is this class
  for?", with the likely week already chosen, and says where the class will land: "This will be WK 6's
  second class". The class goes in the week you choose, whatever the calendar says, so a make-up
  class or a class after a break goes where you want it.
- **A class in the wrong week can be moved**, from the Classes tab, with Move. Its scans and any
  corrections stay exactly as they are.
- **Create a class is gone.** Start taking attendance makes the class. Reading the scans later with
  Get attendance still turns them into classes, for a class taken without the laptop.
- The Classes tab groups classes by the weeks of the sheet, so it always agrees with the sheet.

### Weeks you do not have to know in advance

- **Remove a week** in Sheet setup. A week that holds a class says so and cannot be removed until the
  class is moved, so no class ever falls off the sheet. Remove a week in the middle and the classes
  in the weeks after it move with their weeks.
- **Add a week** in Sheet setup, or choose "a new week" when you start a class and the course runs
  longer than planned.

### Students without a matric number yet

- **Direct-entry students are imported without one.** A row with a name and no matric number is no
  longer left out; it is imported and marked "no matric number yet". Importing the same list again
  does not make them twice, and a later list that carries their number fills it in.
- **Names and matric numbers are editable on the sheet.** Select a student's name or matric number to
  correct it, or to add the number when it comes. They keep their fingerprints and their attendance.
  A student without one shows "no matric yet" on the sheet. A corrected name is sent to the terminal
  straight away, because it shows the name at every scan.

### Updating from 0.1.4 or earlier

Run the installer over the old one with Herewise closed. Your register is kept, and its format is
updated on first start with a copy of it kept as it was, listed under Backup as "Before an update".

## 0.1.4

Attendance is now taken the way it happens in a room, and the attendance sheet is redesigned.

### Taking attendance

- **Start taking attendance, on the course.** Bring the terminal and the laptop, open the course and
  press Start taking attendance. Each student scans, and appears as present within a couple of
  seconds. Nobody is marked absent while it is open: only when you press **End attendance** does
  everybody who did not scan become absent. It is not timed; it stays open until you end it.
- **The screen is built to be read from a step away**: how many are present in large figures, who has
  just scanned at the top with the time, and a searchable list of who has not yet.
- **More than one class a week.** Each class you take goes into its own box in its week on the
  sheet, and a week gains a box when you hold more classes in it than it was set up with. The first
  class you take sets week 1 to the Monday of that week if nobody had set it.
- **Only scans made between Start and End count.** Starting sets the terminal's clock from the
  laptop first, because the two clocks decide which scans fall inside the class, and it refuses to
  start if the terminal is not answering.
- **A loose cable does not lose anything.** If the terminal stops answering during the class the
  screen says so and the class stays open; the terminal keeps every scan, and they come in as soon as
  it answers. Ending reads the terminal once more, so a scan made in the last seconds still counts.
- **Ended late?** End attendance lets you give the time the class really finished, so scans made
  after it do not count.
- While a class is taking attendance, a line at the top of every screen says so, an open class counts
  in no percentage or total, enrolment waits for it to end, and an export shows its boxes blank
  rather than marking anybody absent.
- Adding a class by hand, and reading the scans later with Get attendance, both still work, for a
  class taken without the laptop.

### The attendance sheet

- **Nothing is cut off.** Matric numbers and names are measured and given the room they need; a very
  long name is cut at a sensible width and shown in full when you point at it.
- **The sheet fills the window**, with the weeks sharing the width, and **each week shows the date it
  starts** under its name.
- **Cleaner**: lines between rows and between weeks only, slightly larger text, and the row under the
  pointer is shaded so it is easy to follow across the weeks.
- **One toolbar**: search and classes held on the left; row height, Sheet setup and both exports on the
  right. Start taking attendance is the one main button on a course.
- The sheet and the course header now quote the same number of planned classes.

### Updating from 0.1.3 or earlier

Run the installer over the old one with Herewise closed. Your register is kept, and its format is
updated on first start with a copy of it kept as it was, listed under Backup as "Before an update".

## 0.1.3

What a third run found: Enrol said it was waiting for the finger, and the terminal asked for nothing.

### The terminal that stops asking

- **The terminal can stop taking captures, and Herewise can now restart it.** On the K40 the
  terminal answered every request to enrol with "OK" and did nothing, for over an hour, whatever
  was sent to it. Restarting it cured it at once. **Restart the terminal** now sits beside **Stop
  the capture** while Herewise waits for a finger, and on the Device screen. The terminal's screen
  goes dark and comes back, in 25 to 35 seconds on the K40 it was tried on, a bar counts it, and
  nothing on the terminal is lost: its people and fingerprints were all there afterwards. What makes a terminal do this is not
  known yet. A capture that finishes, one that is stopped and one that is left to time out were all
  tried, and none of them does it.
- **The waiting message says what you should be seeing.** It counts down the minute the terminal is
  given, and says that the terminal's own screen should be asking for a finger now, and what to do
  if it is not. You are the only one who can see that, and before this the screen and the terminal
  could disagree for a full minute with nothing said.
- **A capture that ends with nothing now offers the way round**: restart the terminal and try again,
  or enrol the finger at the terminal's own menu and read the terminal back here. A fingerprint
  enrolled at the keypad counts exactly the same.

### Also fixed

- **Remove, beside a captured finger, now works.** It had never worked on a real terminal: the
  library Herewise uses to talk to the terminal fails on the way it was asked, and the tests had no
  way to notice. It was found while cleaning up after a test on the K40.
- **A successful capture says "captured" and nothing else.** It used to add "Device reported
  not_captured, but the template is on the device, so it was saved", which is the normal way this
  terminal answers and not something anyone needed to read.
- The countdown no longer says its number twice ("57 57 seconds left").
- What the terminal was asked and what it answered now go into the log file, without names or
  keypad passwords, so a fault on somebody else's computer can be traced afterwards. Tonight's three
  failed captures had left no trace there at all.

### Updating from 0.1.2, 0.1.1 or 0.1.0

Run the installer over the old one with Herewise closed. Your register is not touched. Herewise is
still unsigned, so Windows still shows "Windows protected your PC" the first time; the reasoning, and
the checksum to run instead, are under 0.1.0 below.

## 0.1.2

What a second run found, with a department's roster on a real terminal.

### The faults

- **Every PDF export failed with "Internal Server Error".** Export PDF, the eligibility list, the
  eligibility notice, attendance so far and the at-risk list: all of them, in the installed program
  only. A library the PDFs need had been left out of the build to save space, and nothing but the
  built program could show it. Every Excel and CSV export was fine throughout. All ten exports are
  now asked for and checked whenever a build is made.
- **The terminal said "connected" after the cable came out.** The top bar only found out when a
  screen happened to talk to the terminal, so on Today, Courses or Students it kept saying so. It
  now asks the terminal itself every twenty seconds, and again the moment you come back to the
  window, and says when it last checked. The check does not take the terminal out of service, so a
  student can be scanning while it happens.
- **After emptying the terminal, Enrol said it was waiting for a finger and the terminal showed
  nothing.** A terminal emptied from its own keypad leaves Herewise thinking everybody is still on
  it, and a capture aimed at somebody who is not there waits for a finger that can never come. A
  capture now writes the student to the terminal first, every time.
- **Herewise opened behind whatever was already on the screen.** Windows will not let a program
  take the foreground unless it already has it, and Herewise takes a few seconds to start, so by
  the time its window existed it had lost the right to come forward. It now raises itself and asks
  properly, and if Windows still says no, it flashes its taskbar button instead of sitting silently
  behind another window.
- **Choosing a student out of turn threw away your place in the list.** It scrolled back to the top
  where the card is. The card follows you down the page instead, so the capture is always one press
  away and the list stays where you left it.

### What you asked for

- **Delete a course, a class or a level, from the page each one lives on.** Courses has a Delete on
  every row and every card; a class has one on its row, cancelled or not; Levels has Remove on
  every row. Each is offered whether or not it can be used, and where it cannot, it says what is on
  it: "On it: 23 classes, 4 courses, 258 students and 1 roster import". Nothing has to be hunted
  for, and nothing disappears without saying why.
- **What can never be deleted is a signed decision**, and only that: a correction, a correction
  request, an excused absence. A course or a class that has one is refused, and cancelling a class
  is offered instead, which takes it out of every total and leaves the record where it is. A level
  goes when nothing points at it: to be rid of one that has students, take its roster import back
  out first and the students go with it.
- **A scan is never deleted by any of this, and never was.** Deleting a course or a class takes
  away the classes that counted the scans, not the scans: they belong to the terminal's log rather
  than to a course, and another class covering the same time counts them again. Herewise used to
  refuse a course because scans fell inside its classes, and say "attendance that has been recorded
  is never deleted", which implied those scans would go and left a course impossible to be rid of
  for a reason that was not true. The screens now state how many scans fell inside it and what
  happens to them, which is nothing.
- **Add students by hand.** "Add carry-over students" is now "Add students", and offers one student
  by name, matric number and level, or a whole list pasted in. It always could create a student it
  had never seen; the name and the paste box hid that.
- **Forget the fingerprints in this register**, on Device, for when the terminal has been emptied or
  reset by somebody else and Herewise is left claiming fingerprints that are no longer on it. It
  removes a record, not a fingerprint: the fingerprints themselves live on the terminal, so Check
  what is on it puts them straight back if they are still there.
- **A bar while something long is happening, and a plain sentence when it is done.** Sending a level
  counts the people as the terminal takes them; emptying counts them as they come off; reading the
  scans says what it is doing until it knows how many there are. Where the number is not known, it
  says so instead of drawing a bar that pretends to know.

### Importing a roster

- **A department's own workbook imports as it is.** The portal's list has its column names on the
  first row; a departmental spreadsheet opens with the university's name, the session and a title,
  and names its columns five or six rows down. Herewise refused those on the first row it read.
  It now looks down the first twenty rows for the row that names the columns.
- **One workbook with a sheet per year works.** Importing 200 Level reads the sheet named for 200,
  whatever else is on the tab: "200 Level", "300L" and "400 Level " are all matched on their
  number. A file with several sheets and none for the level you are importing into says so, and
  lists the sheets it does have, instead of quietly importing the first one.
- **The line numbers in a preview are the ones in your own file.** They counted from the header
  before, so "line 8" meant something different from row 8 of the spreadsheet on the screen.

### The screens

- The page is centred instead of sitting in the left 1,200px of a maximised window.
- The Levels capacity is a band of figures rather than a card with an empty half beside it.
- The attendance sheet's row-height control sits over the sheet it changes, instead of under Export
  PDF where it read as an export that had fallen off the row.
- "2 cancelleds" is "2 classes cancelled", and a cancellation note is quoted rather than run into
  the sentence after it.

### Updating from 0.1.1 or 0.1.0

Run the installer over the old one with Herewise closed. Your register is not touched: it lives in
`%LOCALAPPDATA%\Herewise`, apart from the program. Coming from 0.1.0, the first start updates the
register's format and keeps a copy of it as it was, listed under Backup as "Before an update".

Herewise is still unsigned, so Windows still shows "Windows protected your PC" the first time. The
reasoning, and the checksum to run instead, are under 0.1.0 below.

## 0.1.1

What the first real run found. Everything here was reported by somebody using 0.1.0 with a
department's own roster on a real K40, or measured while fixing what they reported.

### The faults reported

- **A roster downloaded from the portal would not import.** The file is a `.xls` that the portal
  writes as HTML with a spreadsheet's name, and Herewise said only that it could not read it. It
  now reads the real thing, says so plainly when a file is that kind of `.xls`, and takes
  `.xlsx` and CSV as before.
- **Exports arrived as `export.txt`.** Every download from inside the Herewise window was
  cancelled by the window itself and saved under the wrong name. PDF and Excel exports, the
  eligibility list, the activity log and backups all save properly now, each under the name
  Herewise gives it.
- **"Attendance sheet did not load" when making a sheet for a new course.** New course led
  nowhere: the screen behind the link did not exist. It does now, and it leads straight into the
  sheet setup for the course it just made.
- **Enrolment could not be steered.** You could not choose who to enrol, could not see who had
  already been done, could not remove a fingerprint recorded by mistake, and pressing Enrol said
  the capture had not started while the terminal was plainly waiting for a finger. All four are
  fixed: the list of everyone on the level is searchable and every row can be chosen, each
  student's two fingers are shown with what has been recorded, either can be removed on its own,
  and the screen now says what the terminal is actually doing.
- **A capture could not be stopped.** Starting one by mistake meant waiting out the terminal's own
  minute. Stopping it now takes about two seconds, measured on the K40.
- **A roster imported into the wrong level could not be taken back.** Past imports are listed with
  what each one created, and one whose students have not yet scanned, been corrected, been
  excused, been enrolled or been sent to the terminal can be taken back out. One whose students
  have any of those says so instead of half-doing it.
- **There was no way to clear the terminal.** Device now shows what is really on it against what
  the register thinks, and offers taking one person off, emptying every person and fingerprint, and
  clearing the scans, each stating exactly what it does and what it leaves alone.
- **The rail said "No students yet" after a roster had been imported.** It was read once at sign-in
  and never again. It now counts every level in the session, names the level when there is only
  one, and says when the real answer is that no session has been made current.
- **Settings and Device hid their own screens.** Accounts, Roles, the activity log, Backup, About
  and the device screens were reachable only from inside another screen. Each section's screens are
  listed in the rail while you are in it.

### The screens themselves

- **Nothing is hidden off the side of a table any more.** Excused absences at a narrow window put
  three columns and the Withdraw button past the edge of the frame with nothing to scroll. A table
  wider than its frame now scrolls, says so, and can be reached with the keyboard.
- **Long lists stop at 25 rows** with one press for the rest. Enrolment was fifteen thousand pixels
  of scrolling; choosing a Super Admin was a radio button for every person on the terminal and is a
  search now.
- **Settings reads as a settings screen**: each one a row with what it is on the left and what it
  is set to on the right, Save in a bar at the foot of the window, and a box the size of the number
  that goes in it rather than the width of the page.
- **A dropdown looks like a dropdown.** The arrow had gone missing, so a list you could open and a
  number you could type were the same shape.
- **Paragraphs are a readable width** instead of running the full width of the window.
- **The rail keeps its words** down to a much narrower window than before, and each icon carries its
  name when there is no room for the word.
- **Remove is held away from Import roster** on Levels, so a press meant for one cannot land on the
  other.
- Buttons in a row are the same size as each other whatever is written under them, links that are a
  whole row's action are big enough to hit, and the tick in a student's timeline is readable.

### Under it

- Two new checks that the next change has to pass: `node scripts/check_layout.mjs <port>` walks
  every screen at four window widths looking for anything that overflows, collides, cannot be hit or
  cannot be read, and both it and the older checks now say which server they measured. They plant
  faults for themselves first and stop if they cannot find them.

### Updating from 0.1.0

Run the new installer over the old one with Herewise closed. Your register is not touched: it lives
in `%LOCALAPPDATA%\Herewise`, apart from the program, and an update replaces only the program. The
register's format changed, so the first start updates it, and a copy of it as it was is taken first
and listed under Backup as "Before an update".

Herewise is still unsigned, so Windows still shows "Windows protected your PC" the first time. The
reasoning, and the checksum to run instead, are under 0.1.0 below and have not changed.

## 0.1.0

The first build anyone other than its authors could install. Built and checked on 2026-09-21.

**Herewise is a window now, not a web address.** It installs into your own user folder, needs no
administrator rights, and opens from the Start menu like any other program. There is no terminal
window to keep open and no browser tab to lose.

### Installing

- `Herewise-Setup-0.1.0.exe` puts the program in `%LOCALAPPDATA%\Programs\Herewise`, adds it to the
  Start menu and the desktop, and lists it in Apps so it can be removed from there.
- **Your register is kept apart from the program**, in `%LOCALAPPDATA%\Herewise`. Installing,
  updating and removing Herewise never touch it.
- Running the installer while Herewise is open changes nothing and asks you to close it first.
- `--quiet` installs without asking, for setting up several computers; it exits with 1 if it
  refused.
- It needs the Microsoft Edge WebView2 Runtime, which Windows 11 and most Windows 10 computers
  already have. Without it Herewise says so and opens in your browser instead. For a computer with
  no internet, put Microsoft's own `MicrosoftEdgeWebView2RuntimeInstallerX64.exe` beside our
  installer and it is installed first, for your user only and without administrator rights.

### Getting started

- **The years are yours to set.** Herewise starts with 100 to 500 Level. Add a 600 or a 700 for a
  course of study that runs that long, remove the ones your department does not run, and rename any
  of them to whatever you call that year. A level keeps its own block of device IDs for good, and
  one that has students, courses or classes on it is never removed by accident: Herewise says what
  is on it instead.
- **Your roster goes in as it comes out of the portal.** The course list downloads as a spreadsheet,
  and Herewise reads it: `.xls`, `.xlsx` or CSV, with no saving-as in between. It reads the heading
  row to find the columns, so "Matric No." and "MATRIC NUMBER" are both understood, and it needs
  only a matric number and a full name. Nothing is written until you have seen the preview.
- **First-run setup**, in five steps: your account, the academic session, the terminal, a review
  where nothing has been written yet, and your first roster. It saves as you go, so you can close
  the app half way through and carry on later. Your password is never part of what it saves.
- **The connection test** walks the cable, this computer's address, the route, the terminal and its
  port, one link at a time, and reads the terminal's serial and firmware at the end. Only the first
  broken link speaks; everything below it says it was not reached, rather than inventing a result.

### Every day

- **Today** shows the last pull, today's classes with their counts, and what is waiting.
- **Get attendance** reads the terminal, stores every scan and works the classes out from them.
  The result shows the scans as they actually arrived, and the gap between two bursts is measured
  from those two bursts.
- **Unassigned classes** is for when two courses share students and Herewise cannot tell which
  class it found. It says how many of the people who scanned are on each candidate course.
- **The class register** lists everyone with their status, and its counts are filters.
- **Corrections** never overwrite a scan. A correction is recorded beside it with a note and the
  name of whoever made it, and both are kept for good. Anyone whose role cannot apply one raises a
  request instead, for somebody else to approve or reject.
- Nobody corrects or excuses the student record their own account is linked to, whatever their
  role allows.

### The register itself

- **The attendance sheet** on screen is the lecturer's own paper sheet: frozen name columns, a
  box per class, and the same layout as the PDF and Excel exports, both of which it downloads.
  Clicking a box corrects it.
- **Percentages** recompute as you change the pass mark or the number of weeks, before anything is
  saved, so the table under the figures can never disagree with them.
- **Eligibility** states the rules it was decided under before it states the decision, and says why
  each name is on the list.
- **Attendance so far** and **Students below the pass mark** are for part way through the term: a
  notice to post with matric numbers and no names, and the lecturer's own at-risk list with what
  each student still needs.
- **Excused absences** take a class out of a student's total rather than counting against them.
- **A student's record** shows every class with the reason for its status, every scan with where
  it came from, every correction and every excused absence, including withdrawn ones.

### The terminal

- **Device** shows the serial, firmware, clock drift and how full the terminal is. When it does not
  answer, every figure that came from it says so rather than showing a stale one.
- **Super Admins**: two seats, because one absence or one cut finger would otherwise lock the menu.
  Removing the last one states what that opens up and asks first.
- **Enrolment** takes two fingers per student and is driven from the keyboard, with the screen
  readable from the terminal itself. Anyone who would rather not give a fingerprint gets a keypad
  password instead, with the reason recorded.
- **Unlock the device menu** and **Clear the scans** both need the terminal's serial typed in, and
  neither claims anything happened when it did not.
- **USB import** is not built. It will be written against a real file exported from this terminal,
  not from documentation, and the screen says so.

### Administration

- **Roles** are rows you create, name and tick for yourself. There is no fixed list of job titles.
  Every screen names the permission it needs, and anything your role does not allow stays on screen
  with the reason written on it rather than disappearing.
- **Accounts** can be given a new password and turned back on after being turned off. If the only
  owner has forgotten their password, the way back is on the computer that holds the register:
  press Windows+R and run
  `"%LOCALAPPDATA%\Programs\Herewise\Herewise.exe" reset-password <username>`. A window asks for
  the new password twice without showing it, and the activity log records that it happened.
- **The activity log** records who did what, in sentences naming the student and the class, and
  cannot be changed or deleted. It narrows by date, by person and by kind, and exports as a CSV.
- **Backup** takes a copy of the whole register, and one is taken automatically after every pull
  that stores new scans. It says plainly that the file holds every keypad password in plain digits,
  so it should be kept where the keys to the terminal's room are kept.
- **Restoring** replaces the whole register with a backup, in two steps. First Herewise looks at the
  file and shows what is in it beside what you have now, and refuses it if it is damaged, is not a
  Herewise register, was made by a newer version, or has nobody in it who could sign in. Then it
  asks for your password. The register as it is now is kept first, as a copy you can restore in the
  same way, so a restore can be undone. Everyone signed in is signed out, because the accounts are
  the backup's now, and the restore is written into the restored register's own activity log.

### Why Windows warns about this, and what to do

The first time you run the installer, Windows shows a blue box headed "Windows protected your PC".
Select **More info**, then **Run anyway**. Nothing is wrong with the file; Windows is telling you it
has not seen it before.

We would rather it did not say that, and we looked properly at stopping it. Buying a code signing
certificate would put the name Emberfig on that box instead of "Unknown publisher", and it would
still warn you. Microsoft decides whether to warn from how many people have downloaded that exact
file, not from the certificate, so anything new is warned about until the downloads add up.
Herewise is carried to a department's computer and installed by hand rather than downloaded by
thousands of people, so they will not add up, and the box would appear either way. We would rather
spend the money on the work than on a line of text.

What is worth doing instead takes ten seconds. Every release lists its files and their SHA-256
checksums in `SHA256SUMS.txt` beside the download. Run this in PowerShell, in the folder you
downloaded to, and check the answer matches the line for that file:

```powershell
Get-FileHash .\Herewise-Setup-0.1.0.exe -Algorithm SHA256
```

If it matches, the file is exactly the one we built. If it does not, do not run it, and tell us.

We will sign Herewise when there is a reason to: if it ever goes on a public download page, or if
the people installing it are told by their own IT policy that they may not run unsigned software.
The checksums stay either way.

### Known, and deliberate

- **USB import is not built**, as above.
- **Sending a whole level to the terminal takes about a minute** and Herewise cannot do anything
  else while it runs. It says so while it works.
- **A backup file contains keypad passwords in plain digits.** Encrypting it, or leaving them out
  and asking for them again on restore, is planned.
- **Made by Emberfig**, on every screen, linking to https://emberfig.com/. It opens in your own
  browser rather than taking the register's window away to a website.
