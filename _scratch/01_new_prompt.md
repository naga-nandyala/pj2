I have a python cli application. (mycli)
I have many dependencies (e.g. msal, msal[broker], azure-core etc).
i want to bundle all these dependencies. 
i want to make this work on MacOS (brew install mycli)
i can not user homebrew Formula as all these dependencies does not have source code. (e.g. pymsalruntime is a binary and does not have source code)
So i have to use homebrew cask

