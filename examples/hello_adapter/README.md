# Hello Aphrodite adapter

This is a working example third-party Aphrodite module adapter.
Copy this directory when you want to make your own module package.

Aphrodite discovers adapters through Python entry points.
It never imports your code directly from the Aphrodite repository.
That means your module can live, build, and ship independently.

## Try it

1. Install this package into the same environment as Aphrodite:

   ```sh
   pip install -e .
   ```

2. Enable the adapter system name:

   ```sh
   export APHRODITE_MODULES=hello
   ```

3. Dispatch a test custom id:

   ```sh
   aphrodite dispatch-test hello:v1:greet:there
   ```

You should see a successful result containing `hello, there!`.
Edit `handle()` in `hello_adapter.py` to add your own actions.
