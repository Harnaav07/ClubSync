# ClubSync
ClubSync is a Soccer Club Management System for Western Tigers Soccer Club.

The system was created using Flask, SQLite, HTML, CSS and JavaScript.

## Main Features

- Secure login
- Admin, Coach and Viewer user roles
- Player management
- Attendance tracking
- Team selection and formations
- Fee management
- Asset management
- Training session management
- Dashboard with live club information
- Football fixtures using the Football-Data.org API

## User Roles

- Admin – full access to manage club information
- Coach – access to coaching and team-related features
- Viewer – read-only access to selected information

## Database

ClubSync uses an SQLite database called `clubsync.db` to store club information.

## API

Football fixture information is retrieved using the Football-Data.org API. The API key is stored securely in a `.env` file.