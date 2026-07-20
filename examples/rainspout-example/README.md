# rainspout-example

The pedagogical Rainspout content package — one handler (Tutorial 1), one
stage (Tutorial 2), an example run config (Tutorial 3), and a
package-contributed verb. This is the shape a new package copies; the
authoring guides in the skeleton's `docs/` are the contract it follows.

```bash
uv add --editable ./rainspout-example   # or: uv pip install -e ./rainspout-example
spout catalog                            # its components are now listed
spout rainspout_example make-data --base-dir ./data/raw
spout run --config src/rainspout_example/configs/example_run.yml
spout test-package rainspout_example
```
