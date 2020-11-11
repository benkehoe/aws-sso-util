.PHONY: build deploy clean

INPUT_DIR ?= .
INPUT_FILES ?= $(INPUT_DIR)/*.yaml

ifdef OUTPUT_DIR
_OUTPUT_DIR = $(OUTPUT_DIR)
PARAMS += --output-dir $(OUTPUT_DIR)
else
_OUTPUT_DIR = $(INPUT_DIR)/templates
endif

OUTPUT_FILES = $(shell [ -d $(_OUTPUT_DIR) ] && find $(_OUTPUT_DIR) -maxdepth 1 -name "*.yaml")

ifdef AWS_SSO_INSTANCE
PARAMS += --instance $(AWS_SSO_INSTANCE)
endif

ifdef TEMPLATE_FILE_SUFFIX
PARAMS += --template-file-suffix $(TEMPLATE_FILE_SUFFIX)
endif

ifdef BASE_TEMPLATE_FILE
PARAMS += --base-template-file $(BASE_TEMPLATE_FILE)
endif

ifdef TEMPLATE_PARAMETERS
PARAMS += --template-parameters $(TEMPLATE_PARAMETERS)
endif

ifdef MAX_RESOURCES_PER_TEMPLATE
PARAMS += --max-resources-per-template $(MAX_RESOURCES_PER_TEMPLATE)
endif

ifdef MAX_CONCURRENT_ASSIGNMENTS
PARAMS += --max-concurrent-assignments $(MAX_CONCURRENT_ASSIGNMENTS)
endif

ifdef EXTRA_ARGS
PARAMS += $(EXTRA_ARGS)
endif

build:
	@echo Building $(INPUT_FILES)
	aws-sso-util cfn $(PARAMS) $(INPUT_FILES)

STACK_PREFIX ?= aws-sso-assignments-

deploy: build
#	@echo Deploying $(OUTPUT_FILES)
	@for FILE in $(OUTPUT_FILES); do \
	  echo Deploying $$FILE; \
	  STACK_NAME=$(STACK_PREFIX)`python -c "import sys, pathlib; print(pathlib.Path(sys.argv[1]).stem)" $$FILE`; \
	  sam deploy --template-file $$FILE --stack-name $$STACK_NAME $(SAM_ARGS); \
	done

clean:
	rm -rf $(_OUTPUT_DIR)

.default: build
